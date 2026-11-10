"""Piloto: converte "quero a nave em (tx, ty)" em movimento contínuo de um controle RELATIVO
(arrastar dedo ou mouse: a nave anda o deslocamento do controle x gain).

- Movimento em passos pequenos (`step` px por evento a `hz` Hz): muitos jogos ignoram saltos grandes.
- Quando o controle chega na borda da área permitida, levanta e recoloca em `home` (não move a nave).
- Latência controle -> vídeo: a posição vista da nave está atrasada; compensamos somando o movimento já
  enviado e ainda não visível no quadro.

O dispositivo só precisa de touch_down(x, y), touch_move(x, y) e touch_up(x, y) (ver interfaces.TouchInput).
`threaded=False` + `clock` próprio: o chamador chama `tick()` (usado no simulador, sem tempo real).
"""
import threading, time, collections, logging

from .config import PilotConfig

log = logging.getLogger("shooter_core")


class RelativePilot:
    def __init__(self, dev, cfg: PilotConfig = None, threaded=True, clock=time.time):
        self.dev = dev
        self.cfg = cfg or PilotConfig()
        self.clock = clock
        self.finger = None                 # posição real do controle (None = solto)
        self.virt = [0.0, 0.0]             # soma de todos os deslocamentos enviados (não "pula" ao reposicionar)
        self.goal = None                   # alvo do controle virtual
        self.hist = collections.deque()    # (t, vx, vy) do controle virtual, para compensar a latência
        self._lock = threading.Lock()
        self._run = threaded
        self._th = None
        if threaded:
            self._th = threading.Thread(target=self._loop, daemon=True)
            self._th.start()

    def virt_at(self, t):
        """Posição do controle virtual no instante t (a mais recente registrada antes de t)."""
        with self._lock:
            best = (self.virt[0], self.virt[1])
            for ht, vx, vy in reversed(self.hist):
                best = (vx, vy)
                if ht <= t:
                    break
            return best

    def predict_ship(self, ship_then, t_then, t_now):
        """Onde a nave vista em t_then deve estar em t_now, pelo movimento do controle enviado nesse intervalo."""
        L, G = self.cfg.latency, self.cfg.gain
        a0 = self.virt_at(t_then - L)
        a1 = self.virt_at(t_now - L)
        return ship_then[0] + (a1[0] - a0[0]) * G, ship_then[1] + (a1[1] - a0[1]) * G

    def steer(self, ship, target, frame_time):
        """ship: posição vista no quadro capturado em frame_time; target: onde a nave deve ir."""
        c = self.cfg
        px, py = self.virt_at(frame_time - c.latency)
        with self._lock:
            pend = ((self.virt[0] - px) * c.gain, (self.virt[1] - py) * c.gain)
            ex = target[0] - (ship[0] + pend[0])
            ey = target[1] - (ship[1] + pend[1])
            if abs(ex) < c.deadband and abs(ey) < c.deadband:
                self.goal = (self.virt[0], self.virt[1])
            else:
                self.goal = (self.virt[0] + ex / c.gain, self.virt[1] + ey / c.gain)

    def nudge(self, dx, dy=0.0):
        """Empurrão RELATIVO (não depende de saber onde a nave está): usado quando a nave some na borda."""
        with self._lock:
            self.goal = (self.virt[0] + dx / self.cfg.gain, self.virt[1] + dy / self.cfg.gain)

    def hold(self):
        """Para de mexer (mantém o controle onde está)."""
        with self._lock:
            self.goal = (self.virt[0], self.virt[1])

    def release(self):
        with self._lock:
            self.goal = None
            if self.finger:
                self.dev.touch_up(*self.finger)
                self.finger = None

    def close(self):
        self._run = False
        if self._th:
            self._th.join(timeout=1)
        self.release()

    # ---------- laço de hz Hz ----------
    def _loop(self):
        period = 1.0 / self.cfg.hz
        nxt = time.perf_counter()
        failing = False
        while self._run:
            try:
                self.tick()
                failing = False
            except Exception:
                if not failing:                  # registra uma vez por sequência de falhas
                    log.exception("pilot tick")
                failing = True
                time.sleep(0.2)
            nxt += period
            time.sleep(max(0.0, nxt - time.perf_counter()))
            if time.perf_counter() - nxt > 0.1:
                nxt = time.perf_counter()

    def tick(self):
        c = self.cfg
        with self._lock:
            if self.goal is None:
                return
            if self.finger is None:
                self.finger = tuple(c.home)
                self.dev.touch_down(*self.finger)
                return
            dx, dy = self.goal[0] - self.virt[0], self.goal[1] - self.virt[1]
            d = (dx * dx + dy * dy) ** 0.5
            if d < 1:
                return
            k = min(1.0, c.step / d)
            mx, my = dx * k, dy * k
            nx, ny = self.finger[0] + mx, self.finger[1] + my
            if not (c.fx[0] <= nx <= c.fx[1] and c.fy[0] <= ny <= c.fy[1]):
                # bateria na borda: levanta e recoloca em home (não move a nave)
                self.dev.touch_up(*self.finger)
                self.finger = tuple(c.home)
                self.dev.touch_down(*self.finger)
                return
            self.finger = (nx, ny)
            self.dev.touch_move(nx, ny)
            self.virt[0] += mx
            self.virt[1] += my
            now = self.clock()
            self.hist.append((now, self.virt[0], self.virt[1]))
            while self.hist and now - self.hist[0][0] > 1.0:
                self.hist.popleft()
