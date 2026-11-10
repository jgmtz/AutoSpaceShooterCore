"""Arena sintética: um shooter vertical mínimo para testar o core sem nenhum jogo de terceiros.

- Inimigos no alto andam de um lado para o outro e disparam padrões (tiro mirado, leque, muro com um vão).
- A nave do jogador atira sozinha reto para cima: ficar na coluna de um inimigo causa dano nele.
- O controle é RELATIVO e com latência (como arrastar o dedo num celular): `VirtualTouch`.
- `render()` desenha um quadro BGR de verdade; o `ArenaAdapter` enxerga esse quadro só por cor (OpenCV),
  como um adaptador de jogo real faria.

    from shooter_core.sim import run_episode
    run_episode(seconds=30, mode="bot")    # -> {'hits': ..., 'kills': ..., ...}
"""
import math, random
import numpy as np
import cv2

from .config import for_screen
from .interfaces import GameAdapter, Observation
from .pilot import RelativePilot
from .loop import DodgeLoop

W, H = 540, 1170                      # metade de 1080 x 2340: mesma proporção de um celular retrato
BULLET_R, SHIP_R, ENEMY_R = 6, 14, 26
HIT_R = 22                            # distância nave-projétil que conta como acerto
SHIP_Y0 = 1000
COL_BG, COL_BULLET, COL_SHIP, COL_ENEMY = (30, 20, 20), (40, 40, 255), (255, 230, 0), (60, 200, 60)


class VirtualTouch:
    """Toque relativo com latência: o movimento do 'dedo' chega na nave `latency` s depois, x gain."""

    def __init__(self, arena, gain=1.12, latency=0.10):
        self.arena, self.gain, self.latency = arena, gain, latency
        self.pos = None

    def touch_down(self, x, y):
        self.pos = (x, y)

    def touch_move(self, x, y):
        if self.pos is not None:
            self.arena.queue.append((self.arena.t + self.latency, (x - self.pos[0]) * self.gain, (y - self.pos[1]) * self.gain))
        self.pos = (x, y)

    def touch_up(self, x, y):
        self.pos = None


class Arena:
    def __init__(self, seed=0, n_enemies=3, difficulty=1.0):
        self.rng = random.Random(seed)
        self.t = 0.0
        self.ship = [W / 2, SHIP_Y0]
        self.queue = []                    # (instante, dx, dy) de movimentos ainda não aplicados
        self.bullets = []                  # [x, y, vx, vy]
        self.enemies = []
        self.hits = self.kills = 0
        self.difficulty = difficulty
        self.aligned_s = 0.0               # tempo na coluna de algum inimigo (ofensiva)
        for i in range(n_enemies):
            self._spawn(i)

    def _spawn(self, i):
        r = self.rng
        self.enemies.append({"x": r.uniform(80, W - 80), "y": r.uniform(140, 360), "vx": r.choice((-1, 1)) * r.uniform(40, 90),
                             "hp": 3.0, "next": self.t + r.uniform(0.3, 1.2), "id": i})

    def step(self, dt):
        self.t += dt
        # controle (com latência)
        due = [q for q in self.queue if q[0] <= self.t]
        self.queue = [q for q in self.queue if q[0] > self.t]
        for _, dx, dy in due:
            self.ship[0] = min(max(self.ship[0] + dx, 0), W)
            self.ship[1] = min(max(self.ship[1] + dy, 600), H - 30)
        sx, sy = self.ship
        # inimigos: andam, atiram, levam dano se a nave está na coluna deles
        aligned = False
        for e in list(self.enemies):
            e["x"] += e["vx"] * dt
            if not 50 < e["x"] < W - 50:
                e["vx"] *= -1
            if abs(e["x"] - sx) < ENEMY_R + 8:
                e["hp"] -= 1.0 * dt
                aligned = True
            if e["hp"] <= 0:
                self.enemies.remove(e)
                self.kills += 1
                self._spawn(e["id"])
                continue
            if self.t >= e["next"]:
                self._fire(e)
        if aligned:
            self.aligned_s += dt
        # projéteis
        keep = []
        for b in self.bullets:
            b[0] += b[2] * dt
            b[1] += b[3] * dt
            if math.hypot(b[0] - sx, b[1] - sy) < HIT_R:
                self.hits += 1
                continue
            if -20 < b[0] < W + 20 and b[1] < H + 20:
                keep.append(b)
        self.bullets = keep

    def _fire(self, e):
        r, k = self.rng, self.difficulty
        sx, sy = self.ship
        v = r.uniform(300, 480) * k
        kind = r.random()
        if kind < 0.45:                                    # tiro mirado (3 em sequência levemente abertos)
            a = math.atan2(sy - e["y"], sx - e["x"])
            for da in (-0.08, 0.0, 0.08):
                self.bullets.append([e["x"], e["y"] + 20, v * math.cos(a + da), v * math.sin(a + da)])
            e["next"] = self.t + r.uniform(0.8, 1.4) / k
        elif kind < 0.85:                                  # leque
            for a in np.linspace(math.radians(55), math.radians(125), 7):
                self.bullets.append([e["x"], e["y"] + 20, v * math.cos(a), v * math.sin(a)])
            e["next"] = self.t + r.uniform(1.0, 1.6) / k
        else:                                              # muro com um vão
            gap = r.uniform(80, W - 80)
            for x in range(15, W, 34):
                if abs(x - gap) > 50:
                    self.bullets.append([float(x), e["y"] + 20, 0.0, v * 0.8])
            e["next"] = self.t + r.uniform(1.5, 2.2) / k

    def render(self):
        img = np.empty((H, W, 3), np.uint8)
        img[:] = COL_BG
        for e in self.enemies:
            x, y = int(e["x"]), int(e["y"])
            cv2.rectangle(img, (x - ENEMY_R, y - ENEMY_R // 2), (x + ENEMY_R, y + ENEMY_R // 2), COL_ENEMY, -1)
        sx, sy = int(self.ship[0]), int(self.ship[1])
        tri = np.array([[sx, sy - SHIP_R - 4], [sx - SHIP_R, sy + SHIP_R], [sx + SHIP_R, sy + SHIP_R]], np.int32)
        cv2.fillPoly(img, [tri], COL_SHIP)
        for x, y, *_ in self.bullets:
            cv2.circle(img, (int(x), int(y)), BULLET_R, COL_BULLET, -1)
        return img


def _blobs(mask, min_area):
    n, _, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
    return [(float(cents[i][0]), float(cents[i][1]), stats[i]) for i in range(1, n) if stats[i][4] >= min_area]


class ArenaAdapter(GameAdapter):
    """Adaptador do jogo de exemplo: tudo por COR, sem acesso ao estado interno da arena."""

    def detect(self, img, ship_hint=None):
        ship_m = cv2.inRange(img, (200, 180, 0), (255, 255, 60))
        foe_m = cv2.inRange(img, (30, 160, 30), (100, 240, 100))
        bul_m = cv2.inRange(img, (0, 0, 200), (90, 90, 255))
        ships = _blobs(ship_m, 60)
        ship = None
        if ships:
            x, y, _ = max(ships, key=lambda b: b[2][4])
            ship = (x, y + 3)                              # centro do triângulo (o centroide fica um pouco abaixo)
        bullets = []
        for x, y, st in _blobs(bul_m, 8):
            w, h, a = st[2], st[3], st[4]
            if w > 2 * BULLET_R + 4 or h > 2 * BULLET_R + 4:   # projéteis colados: divide pela área
                k = max(1, int(round(a / (math.pi * BULLET_R ** 2))))
                x0, y0 = st[0], st[1]
                for i in range(k):
                    bullets.append((x0 + (i + 0.5) * w / k, y0 + (i + 0.5) * h / k))
            else:
                bullets.append((x, y))
        enemies = [(x, y, float(ENEMY_R)) for x, y, _ in _blobs(foe_m, 200)]
        return Observation(ship=ship, bullets=bullets, enemies=enemies)


def make_bot(arena, threaded=False):
    """Core configurado para a arena (tela 540 x 1170) com piloto relativo no relógio da simulação."""
    cfg = for_screen(W, H)
    cfg.planner.prefer_y = SHIP_Y0
    cfg.planner.y_range = (840.0, 1110.0)
    cfg.pilot.fy = (500.0, 1150.0)
    cfg.pilot.home = (W / 2, 850.0)
    cfg.loop.idle_after = 1e9                              # a arena não desacelera com a nave parada
    touch = VirtualTouch(arena, gain=cfg.pilot.gain, latency=0.10)
    pilot = RelativePilot(touch, cfg.pilot, threaded=threaded, clock=lambda: arena.t)
    loop = DodgeLoop(ArenaAdapter(), pilot, cfg, threaded_plan=threaded)
    return loop, pilot


def run_episode(seconds=30.0, mode="bot", seed=0, difficulty=1.0, on_frame=None, offense=True):
    """Simula `seconds` s de jogo. mode: "bot" (core pilotando) ou "idle" (nave parada, para comparar).
    Quadros a 20 por segundo, controle a 60 Hz. Devolve as métricas."""
    arena = Arena(seed=seed, difficulty=difficulty)
    loop, pilot = make_bot(arena)
    if not offense:
        loop.planner.cfg.w_dps = 0.0
    tick, k = 1 / 60, 0
    while arena.t < seconds:
        if mode == "bot":
            pilot.tick()
        arena.step(tick)
        k += 1
        if k % 3 == 0 and mode == "bot":
            ctx = loop.step(arena.render(), arena.t)
            if on_frame:
                on_frame(arena, ctx)
        elif k % 3 == 0 and on_frame:
            on_frame(arena, None)
    loop.close()
    return {"mode": mode, "seconds": seconds, "hits": arena.hits, "kills": arena.kills,
            "hits_per_min": arena.hits * 60 / seconds, "aligned_pct": 100 * arena.aligned_s / seconds}
