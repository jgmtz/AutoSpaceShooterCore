"""Pontos de variação do core: o que cada jogo (produto) precisa implementar.

O core é a parte COMUM a qualquer shooter vertical: rastrear projéteis, planejar a esquiva, ficar na coluna
de tiro dos inimigos e pilotar a nave. O que muda de um jogo para outro fica atrás destas interfaces:

- GameAdapter  -> como ENXERGAR o jogo (detectar nave, projéteis e inimigos num quadro) e regras próprias
                  (ex.: modo defensivo com vida baixa).
- FrameSource  -> de onde vêm os quadros (celular via scrcpy, janela do PC, simulador, vídeo gravado).
- TouchInput   -> como mexer a nave (toque no celular, mouse arrastando, simulador).
"""
from dataclasses import dataclass, field
from typing import Optional, Protocol, Sequence, Tuple, runtime_checkable

Point = Tuple[float, float]


@dataclass
class Observation:
    """O que o adaptador viu num quadro. Coordenadas em px da tela do jogo."""
    ship: Optional[Point] = None                        # centro da nave do jogador (None = não achou)
    bullets: Sequence = field(default_factory=list)     # [(x, y)] projéteis inimigos
    enemies: Sequence = field(default_factory=list)     # [(x, y, r)] inimigos (alvos e obstáculos)
    obstacles: Sequence = field(default_factory=list)   # [(x, y, vx, vy)] perigos extras já com velocidade
    playing: bool = True                                # False = a partida acabou / tela fora do jogo


class GameAdapter:
    """Classe base do adaptador de um jogo. Só `detect` é obrigatório."""

    def detect(self, img, ship_hint=None) -> Observation:
        """img: quadro BGR (numpy). ship_hint: última posição conhecida da nave (para buscar perto)."""
        raise NotImplementedError

    def plan_overrides(self, ctx) -> Optional[dict]:
        """Parâmetros do planejador só para este quadro (w_dps, sigma0, y_min). ctx: loop.FrameContext.
        Ex.: com vida baixa, desligar a ofensiva e aumentar a margem."""
        return None

    def on_frame(self, ctx) -> None:
        """Gancho chamado no fim de cada quadro processado (registro, estatísticas, debug)."""


@runtime_checkable
class TouchInput(Protocol):
    def touch_down(self, x: float, y: float) -> None: ...
    def touch_move(self, x: float, y: float) -> None: ...
    def touch_up(self, x: float, y: float) -> None: ...


@runtime_checkable
class FrameSource(Protocol):
    def next_frame(self, after_idx: int, timeout: float = 1.0):
        """Devolve (idx, img) do quadro mais recente depois de after_idx, ou (after_idx, None)."""
        ...

    @property
    def frame_time(self) -> float:
        """Instante (s) em que o último quadro entregue foi capturado."""
        ...
