"""Loop genérico de jogo: quadro -> adaptador (visão) -> rastreio -> planejador -> piloto.

    loop = DodgeLoop(adapter, pilot, cfg)
    loop.run(frame_source)              # tempo real
    loop.step(img, frame_time)          # um quadro (simulador, testes)

`AsyncPlanner` também é usado sozinho por produtos que têm o próprio loop (ex.: o bot do GWZ): o planejador
roda numa thread enquanto o loop já captura/detecta o próximo quadro, e a própria thread manda o destino ao
piloto assim que fica pronto. Fila de no máximo 1: plano antigo ainda não iniciado é descartado.
"""
import time, logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .config import CoreConfig
from .planner import SpaceTimePlanner, linear_predictor
from .tracking import Tracker
from .ship import ShipEstimator

log = logging.getLogger("shooter_core")


class AsyncPlanner:
    def __init__(self, plan_fn, pilot, t0=0.15, predictor=linear_predictor, threaded=True):
        """plan_fn(ship, predict, t0=, prev_end=, prev_target=, enemies=, **over) -> (alvo, folga, caminho)."""
        self.plan_fn, self.pilot, self.t0, self.predictor = plan_fn, pilot, t0, predictor
        self.shared = {"target": None, "end": None, "fut": None, "clear": None}
        self._ex = ThreadPoolExecutor(max_workers=1) if threaded else None

    def _task(self, ship, vel, ft, enemies, steer_ok, over):
        sh = self.shared
        tgt, clear, path = self.plan_fn(ship, self.predictor(vel), t0=self.t0, prev_end=sh["end"],
                                        prev_target=sh["target"], enemies=enemies, **(over or {}))
        sh["end"], sh["target"], sh["clear"] = path[-1][1:], tgt, clear
        if steer_ok:
            self.pilot.steer(ship, tgt, ft)
        return tgt

    def submit(self, ship, vel, ft, enemies=None, steer_ok=True, over=None):
        """Agenda um plano; devolve o destino mais recente já pronto (ou None)."""
        if self._ex is None:
            return self._task(ship, list(vel), ft, enemies, steer_ok, over)
        f = self.shared["fut"]
        if f is not None and not f.done():
            f.cancel()
        self.shared["fut"] = self._ex.submit(self._task, ship, list(vel), ft, enemies, steer_ok, over)
        return self.shared["target"]

    def reset(self):
        self.shared.update(target=None, end=None, clear=None)

    def close(self):
        if self._ex:
            self._ex.shutdown(wait=False, cancel_futures=True)


@dataclass
class FrameContext:
    """Estado de um quadro, entregue aos ganchos do adaptador."""
    ft: float
    img: object
    obs: object
    ship: tuple = None
    ship_detected: bool = False
    threats: list = field(default_factory=list)    # [(x, y, vx, vy)] tudo que o planejador evita
    enemies: list = field(default_factory=list)
    target: tuple = None
    idle: bool = False
    frames: int = 0


class DodgeLoop:
    def __init__(self, adapter, pilot, cfg: CoreConfig = None, planner=None, tracker=None, threaded_plan=None):
        self.cfg = cfg or CoreConfig()
        self.adapter, self.pilot = adapter, pilot
        self.planner = planner or SpaceTimePlanner(self.cfg.planner)
        self.tracker = tracker or Tracker(self.cfg.tracker)
        predict = getattr(pilot, "predict_ship", None)
        self.ship = ShipEstimator(self.cfg.ship, predict)
        lc = self.cfg.loop
        threaded = lc.plan_async if threaded_plan is None else threaded_plan
        self.aplan = AsyncPlanner(self.planner.plan, pilot, t0=lc.plan_t0, threaded=threaded)
        self.prev_vel, self.coast_prev, self.prev_t = [], [], None
        self.foes_tr, self.t_foes = [], None
        self.t_bullets, self.wiggle_x = -1e9, lc.wiggle_x[0]
        self.target = None
        self.frames = 0

    def step(self, img, ft):
        """Processa um quadro. Devolve FrameContext (ctx.obs.playing=False quando a partida acabou)."""
        lc = self.cfg.loop
        obs = self.adapter.detect(img, ship_hint=self.ship.ship)
        ctx = FrameContext(ft, img, obs, frames=self.frames)
        if not obs.playing:
            return ctx
        st = self.ship.update(obs.ship, ft)
        ctx.ship, ctx.ship_detected = st.pos, st.detected
        if st.pos is None or st.lost:
            self.pilot.hold()
            self.adapter.on_frame(ctx)
            return ctx
        ship = st.pos
        dt = ft - self.prev_t if self.prev_t and ft - self.prev_t < lc.max_dt else 0
        vel = self.tracker.update(self.prev_vel, list(obs.bullets), dt, store_turn=True)
        tracked = vel
        self.coast_prev = self.tracker.coast(self.prev_vel, vel, self.coast_prev, dt, ship)
        vel = vel + [(x, y, vx, vy) for x, y, vx, vy, _ in self.coast_prev]
        self.prev_vel, self.prev_t = tracked, ft
        # inimigos: velocidade pelo rastreador; os que descem/estão perto viram obstáculo móvel
        foes = list(obs.enemies)
        dtf = ft - self.t_foes if self.t_foes is not None and ft - self.t_foes < 0.6 else 0
        self.foes_tr = self.tracker.update(self.foes_tr, [(e[0], e[1]) for e in foes], dtf)
        self.t_foes = ft
        vel = vel + self.tracker.enemy_points(self.foes_tr, ship) + list(obs.obstacles)
        ctx.threats, ctx.enemies = vel, foes
        if vel:
            self.t_bullets = ft
        if ft - self.t_bullets > lc.idle_after and not foes:
            # sem perigo e sem alvo: vai e volta (alguns jogos desaceleram com a nave parada)
            if abs(ship[0] - self.wiggle_x) < 40:
                self.wiggle_x = lc.wiggle_x[1] if self.wiggle_x == lc.wiggle_x[0] else lc.wiggle_x[0]
            self.target = (self.wiggle_x, ship[1])
            ctx.idle = True
            self.pilot.steer(ship, self.target, ft)
        else:
            over = self.adapter.plan_overrides(ctx)
            tgt = self.aplan.submit(ship, vel, ft, enemies=foes or None, steer_ok=True, over=over)
            self.target = tgt or self.target or ship
        ctx.target = self.target
        self.frames += 1
        self.adapter.on_frame(ctx)
        return ctx

    def run(self, source, max_seconds=None):
        """Tempo real: processa sempre o quadro mais recente até a partida acabar ou max_seconds."""
        t_start, idx = time.time(), 0
        try:
            while max_seconds is None or time.time() - t_start < max_seconds:
                idx, img = source.next_frame(idx, timeout=1.0)
                if img is None:
                    continue
                ctx = self.step(img, source.frame_time)
                if not ctx.obs.playing:
                    log.info("loop: partida acabou (%d quadros)", self.frames)
                    return ctx
        finally:
            self.pilot.release()
        return None

    def close(self):
        self.aplan.close()
