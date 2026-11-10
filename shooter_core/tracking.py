"""Rastreio de projéteis e inimigos entre quadros: posição -> (x, y, vx, vy).

- `Tracker.update`: associação 1-para-1 usando a velocidade que cada objeto já tinha (previsão + portão
  proporcional ao deslocamento, casamento guloso pelo menor erro, suavização da velocidade).
- `Tracker.coast`: projéteis que SOMEM do detector (explosão por cima, sobreposição com a nave) continuam
  previstos em linha reta por um tempo curto, só perto da nave.
- `Tracker.enemy_points`: inimigos que descem (ou estão perto) viram pontos-obstáculo móveis, tratados como
  projéteis pelo planejador.

Um mesmo Tracker pode rastrear várias listas (balas, inimigos, drones): o histórico é ligado à lista
devolvida, e a próxima chamada recebe essa mesma lista como `prev`.
"""
import math
import numpy as np

from .config import TrackerConfig


def _tkey(x, y):
    return (int(x) // 4, int(y) // 4)


class Tracker:
    def __init__(self, cfg: TrackerConfig = None):
        self.cfg = cfg or TrackerConfig()
        self.turn = {}       # (x//4, y//4) do projétil -> giro suavizado (graus/s), do último update(store_turn=True)
        self._hist = {}
        self._age = {}

    def update(self, prev, cur, dt, smooth=None, store_turn=False):
        """prev: saída anterior [(x, y, vx, vy)]; cur: detecções novas [(x, y, ...)]; dt em s.
        Devolve [(x, y, vx, vy)] na ordem de `cur`."""
        c = self.cfg
        smooth = c.smooth if smooth is None else smooth
        dv = tuple(c.default_v)
        if dt <= 0 or not prev:
            return [(x, y) + dv for x, y, *_ in cur]
        pairs = []
        for i, (x, y, *_) in enumerate(cur):
            for j, (px, py, pvx, pvy) in enumerate(prev):
                qx, qy = px + pvx * dt, py + pvy * dt
                gate = c.gate_base + c.gate_k * math.hypot(pvx, pvy) * dt
                d = math.hypot(x - qx, y - qy)
                if d < gate:
                    pairs.append((d, i, j))
        pairs.sort()
        used_i, used_j, match = set(), set(), {}
        for d, i, j in pairs:
            if i not in used_i and j not in used_j:
                used_i.add(i)
                used_j.add(j)
                match[i] = j
        out = []
        turn = {}
        for i, (x, y, *_) in enumerate(cur):
            if i in match:
                px, py, pvx, pvy = prev[match[i]]
                mvx, mvy = (x - px) / dt, (y - py) / dt
                vx, vy = smooth * pvx + (1 - smooth) * mvx, smooth * pvy + (1 - smooth) * mvy
                if store_turn and math.hypot(pvx, pvy) > c.turn_min_speed:
                    a = (math.atan2(vy, vx) - math.atan2(pvy, pvx) + math.pi) % (2 * math.pi) - math.pi
                    w = abs(math.degrees(a)) / dt
                    turn[_tkey(x, y)] = 0.6 * self.turn.get(_tkey(px, py), w) + 0.4 * w
            else:
                # objeto novo: o anterior mais próximo ainda sem dono, se o deslocamento for plausível
                best, bd = None, (c.v_max * dt) ** 2
                for j, (px, py, *_) in enumerate(prev):
                    if j in used_j or y < py - 0.2 * c.v_max * dt:
                        continue
                    d = (x - px) ** 2 + (y - py) ** 2
                    if d < bd:
                        best, bd = j, d
                if best is not None:
                    used_j.add(best)
                    vx, vy = (x - prev[best][0]) / dt, (y - prev[best][1]) / dt
                else:
                    vx, vy = dv
            if math.hypot(vx, vy) > c.v_max or vy < c.max_up:
                vx, vy = dv
            out.append((x, y, vx, vy))
        # histórico (idade de cada objeto; reta nas últimas lsq_n observações, se ligado)
        ph = self._hist.get(id(prev))
        if ph is not None and len(ph) != len(prev):
            ph = None
        pa = self._age.get(id(prev))
        hist, ages = [], []
        for i, (x, y, vx, vy) in enumerate(out):
            h = []
            age = 1
            if i in match and ph is not None and match[i] < len(ph):
                h = ph[match[i]]
                age = (pa[match[i]] if pa is not None and match[i] < len(pa) else len(h)) + 1
            t_last = h[-1][0] if h else 0.0
            h = (h + [(t_last + dt, x, y)])[-max(int(c.lsq_n), 2):]
            ages.append(age)
            if c.lsq_n > 1 and len(h) >= c.lsq_n and i in match:
                T = np.array([p[0] for p in h]); X = np.array([p[1] for p in h]); Y = np.array([p[2] for p in h])
                T = T - T.mean()
                den = float((T * T).sum())
                if den > 1e-9:
                    lvx, lvy = float((T * (X - X.mean())).sum() / den), float((T * (Y - Y.mean())).sum() / den)
                    if math.hypot(lvx, lvy) <= c.v_max and lvy >= c.max_up:
                        out[i] = (x, y, lvx, lvy)
            hist.append(h)
        self._hist[id(out)] = hist
        self._age[id(out)] = ages
        while len(self._hist) > 12:
            k0 = next(iter(self._hist))
            self._hist.pop(k0)
            self._age.pop(k0, None)
        if c.neighbor_r > 0:
            known = [(o[0], o[1], o[2], o[3]) for i, o in enumerate(out) if i in match]
            for k, (x, y, vx, vy) in enumerate(out):
                if k in match or (vx, vy) != dv or not known:
                    continue
                d, nb = min(((x - a) ** 2 + (y - b) ** 2, (va, vb)) for a, b, va, vb in known)
                if d < c.neighbor_r ** 2:
                    out[k] = (x, y) + nb
        if store_turn:
            self.turn.clear()
            self.turn.update(turn)
        return out

    def ages_of(self, lst):
        """Quantas vezes cada objeto de uma lista devolvida por update() já foi visto (None se desconhecido)."""
        a = self._age.get(id(lst))
        return a if a is not None and len(a) == len(lst) else None

    def coast(self, prev_vel, vel, coast_prev, dt, ship, max_age=None, near=None, vmin=None):
        """Projéteis que sumiram continuam previstos por até max_age s.
        prev_vel: rastreados no quadro anterior; vel: os deste quadro; coast_prev: [(x, y, vx, vy, idade)]
        lembrados antes. Devolve a nova lista de lembrados."""
        c = self.cfg
        max_age = c.coast_s if max_age is None else max_age
        near = c.coast_near if near is None else near
        vmin = c.coast_vmin if vmin is None else vmin
        if dt <= 0:
            return []
        cand = [(x + vx * dt, y + vy * dt, vx, vy, age + dt) for x, y, vx, vy, age in coast_prev]
        cand += [(x + vx * dt, y + vy * dt, vx, vy, dt) for x, y, vx, vy in prev_vel
                 if math.hypot(vx, vy) > vmin and all(math.hypot(x + vx * dt - a, y + vy * dt - b) > 30 for a, b, *_ in cand)]
        keep = []
        for x, y, vx, vy, age in cand:
            if age <= max_age and (near <= 0 or math.hypot(x - ship[0], y - ship[1]) < near) and \
                    all(math.hypot(x - a, y - b) > 60 for a, b, *_ in vel):
                keep.append((x, y, vx, vy, age))
        return keep

    def enemy_points(self, tracked, ship):
        """tracked = [(x, y, vx, vy)] dos inimigos; devolve pontos-obstáculo (x, y, vx, vy) (corpo em 3 pontos)."""
        c = self.cfg
        if not c.enemy_obst or ship is None:
            return []
        out = []
        for x, y, vx, vy in tracked:
            if not (ship[1] - c.enemy_above < y < ship[1] + c.enemy_below):
                continue
            d = math.hypot(x - ship[0], y - ship[1])
            if d < c.enemy_self:
                continue          # "inimigo" colado no centro da nave = falso positivo da própria nave
            if vy > c.enemy_vy_min or d < c.enemy_near:
                vx_, vy_ = (vx, vy) if math.hypot(vx, vy) < c.v_max else (0.0, 0.0)
                out += [(x + ox, y, vx_, vy_) for ox in (-c.enemy_half, 0.0, c.enemy_half)]
        return out
