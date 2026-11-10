"""Estimativa robusta da posição da nave.

A detecção da nave falha (flash de dano, nave piscando, efeitos por cima) e às vezes "pula" para outra coisa
(asas, mísseis, raios). O piloto sabe exatamente quanto o controle andou, então:
  1. salto impossível em pouco tempo (> teleport_px em < teleport_dt s) = leitura descartada;
  2. leitura longe da posição prevista pelo controle (última detectada + controle x gain) = descartada,
     a não ser que o conflito dure mais que trust_s (aí a previsão é que derivou);
  3. nave sumida há até hold_s: posição estimada pelo controle a partir da última detecção.
"""
from dataclasses import dataclass

from .config import ShipConfig


@dataclass
class ShipState:
    pos: tuple = None          # posição usada neste quadro (detectada ou estimada); None = perdida
    detected: bool = False     # a detecção deste quadro foi aceita
    lost: bool = True          # sem detecção aceita há mais de hold_s


class ShipEstimator:
    def __init__(self, cfg: ShipConfig = None, predict=None):
        """predict(ship_then, t_then, t_now) -> (x, y): previsão pelo controle (RelativePilot.predict_ship).
        Sem predict, a nave sumida fica na última posição."""
        self.cfg = cfg or ShipConfig()
        self.predict = predict
        self.ship = None             # última posição usada
        self.seen_t = 0.0            # instante da última detecção aceita
        self.det = None              # última posição DETECTADA (base da previsão)
        self.det_t = 0.0
        self.reject_since = None
        self.rejects = 0

    def accept(self, detected, ft):
        """Aplica os filtros 1 e 2. Devolve a detecção aceita ou None."""
        c = self.cfg
        d = detected
        if d is not None and self.ship is not None and ft - self.seen_t < c.teleport_dt and \
                ((d[0] - self.ship[0]) ** 2 + (d[1] - self.ship[1]) ** 2) ** 0.5 > c.teleport_px:
            d = None
        if d is not None and self.predict is not None and self.det is not None and 0 < ft - self.det_t < c.jump_window:
            px, py = self.predict(self.det, self.det_t, ft)
            lim = c.jump_px + c.jump_v * (ft - self.det_t)
            if ((d[0] - px) ** 2 + (d[1] - py) ** 2) ** 0.5 > lim:
                if self.reject_since is None:
                    self.reject_since = ft
                if ft - self.reject_since < c.trust_s:
                    d = None
                    self.rejects += 1
                else:
                    self.reject_since = None
            else:
                self.reject_since = None
        return d

    def update(self, detected, ft):
        """detected: (x, y) ou None. Devolve ShipState para este quadro."""
        c = self.cfg
        d = self.accept(detected, ft)
        if d is None:
            if self.ship is None or ft - self.seen_t > c.hold_s:
                return ShipState(self.ship, False, True)
            pos = self.ship
            if self.det is not None and self.predict is not None:
                px, py = self.predict(self.det, self.det_t, ft)
                x0, x1, y0, y1 = c.bounds
                pos = (min(max(px, x0), x1), min(max(py, y0), y1))
            self.ship = pos
            return ShipState(pos, False, False)
        self.seen_t = ft
        self.det, self.det_t = d, ft
        self.ship = d
        return ShipState(d, True, False)
