"""Planejador de esquiva no ESPAÇO-TEMPO: caminho que MAXIMIZA a menor folga até os projéteis.

Grade de posições (x, y) x passos de tempo. Em cada passo a nave pode ir para uma casa vizinha alcançável
(pela velocidade dela) ou ficar. Folga de uma casa num instante = menor distância aos projéteis previstos MENOS
a incerteza da previsão (cresce com o tempo). Valor de um caminho = a pior folga ao longo dele (programação
dinâmica "maximin"); entre caminhos de mesma folga (arredondada), vence o mais barato (menos movimento, perto
da posição preferida e, com a ofensiva ligada, na coluna de tiro dos inimigos).

Refeito a cada quadro (horizonte deslizante): o destino é o ponto do caminho em t0 + lead.

`predict(t)` -> array (n, 2) dos projéteis no instante t (s a partir de agora). Assim o MESMO planejador roda
com a previsão linear (`linear_predictor`) ou com o futuro verdadeiro (oráculo, em simulador).

Ponto de variação: `aim_cost` (ofensiva). O padrão supõe armas que atiram reto para cima; um jogo com mira
diferente sobrescreve esse método numa subclasse.
"""
import math
import numpy as np

from .config import PlannerConfig


class SpaceTimePlanner:
    def __init__(self, cfg: PlannerConfig = None):
        self.cfg = cfg or PlannerConfig()
        self.setup()

    # ---------- grade ----------
    def setup(self):
        """(Re)monta a grade e os vizinhos alcançáveis (chamar depois de mudar campos de geometria do cfg)."""
        c = self.cfg
        xs = np.arange(c.x_range[0], c.x_range[1] + 1, c.gx_step)
        ys = np.arange(c.y_range[0], c.y_range[1] + 1, c.gy_step)
        self.GX, self.GY = np.meshgrid(xs, ys)
        self._C = np.stack([self.GX.ravel(), self.GY.ravel()], 1).astype(np.float32)
        self._K = self._reach_kernel()
        self._KC = np.array([c.w_move * math.hypot(dx * c.gx_step, dy * c.gy_step) for dy, dx in self._K])
        self._POSC = c.dt * (c.w_center * np.abs(self.GX - c.prefer_x) / 100 + c.w_low * np.abs(self.GY - c.prefer_y) / 100)
        H, Wd = self.GX.shape
        self._PAD = max(max(abs(dy), abs(dx)) for dy, dx in self._K)
        Hp, Wp = H + 2 * self._PAD, Wd + 2 * self._PAD
        self._VP = np.full((Hp, Wp), -np.inf)
        self._CP = np.full((Hp, Wp), np.inf)
        yy, xx = np.mgrid[0:H, 0:Wd]
        self._IDX = np.stack([((yy + self._PAD - dy) * Wp + (xx + self._PAD - dx)).ravel() for dy, dx in self._K])
        self._AR = np.arange(H * Wd)

    def _reach_kernel(self):
        """Deslocamentos de casa alcançáveis em dt (elipse pela velocidade)."""
        c = self.cfg
        rx = int(c.speed * c.dt // c.gx_step)
        ry = int(c.speed * c.dt // c.gy_step)
        ks = []
        for dy in range(-max(ry, 0), max(ry, 0) + 1):
            for dx in range(-max(rx, 0), max(rx, 0) + 1):
                if (dx * c.gx_step) ** 2 + (dy * c.gy_step) ** 2 <= (c.speed * c.dt + 1) ** 2:
                    ks.append((dy, dx))
        return ks or [(0, 0)]

    def _shift_max(self, V, cost):
        """Para cada casa: melhor (folga quantizada, -custo) entre os vizinhos alcançáveis no passo anterior."""
        H, Wd = V.shape
        r = self._PAD
        self._VP[r:r + H, r:r + Wd] = V
        self._CP[r:r + H, r:r + Wd] = cost
        SV = self._VP.ravel()[self._IDX]
        SC = self._CP.ravel()[self._IDX] + self._KC[:, None]
        key = np.floor(SV / self.cfg.quant) * 1e4 - SC
        arg = key.argmax(0)
        cols = self._AR
        return SV[arg, cols].reshape(H, Wd), SC[arg, cols].reshape(H, Wd), arg.reshape(H, Wd).astype(np.int32)

    # ---------- ofensiva (ponto de variação) ----------
    def aim_cost(self, enemies, ship_y):
        """Mapa (H, W) de 0 (na coluna de tiro de um inimigo acima da nave) a 1 (fora de qualquer coluna).
        enemies: [(x, y, ...)]. Devolve None se não há alvo."""
        c = self.cfg
        E = [(ex, ey) for ex, ey, *_ in enemies if ey < ship_y - c.aim_min_dy]
        if not E:
            return None
        cov = np.zeros(self.GX.shape[1])
        xs = self.GX[0]
        for ex, ey in E:
            cov = np.maximum(cov, np.exp(-((xs - ex) / c.aim_w) ** 2))
        return np.broadcast_to(1.0 - np.clip(cov, 0, 1), self.GX.shape)

    # ---------- plano ----------
    def start_after(self, ship, prev_target, t0):
        """Onde a nave estará quando o novo comando valer: até lá ela segue indo para o destino anterior."""
        if prev_target is None:
            return ship
        dx, dy = prev_target[0] - ship[0], prev_target[1] - ship[1]
        d = math.hypot(dx, dy)
        if d < 1:
            return ship
        k = min(1.0, self.cfg.real_speed * t0 / d)
        return (ship[0] + dx * k, ship[1] + dy * k)

    def plan(self, ship, predict, t0=0.10, prev_end=None, prev_target=None, enemies=None,
             w_dps=None, sigma0=None, y_min=None):
        """Devolve (destino (x, y), folga do melhor caminho em px, caminho [(t, x, y)]).
        prev_target: destino em vigor (a nave continua indo para ele durante t0).
        prev_end: fim do caminho do plano anterior (evita trocar de rota sem motivo).
        enemies: [(x, y[, r])] para o termo de ofensiva.
        w_dps / sigma0 / y_min: sobrescrevem só nesta chamada (ex.: modo defensivo). y_min = custo forte acima dela."""
        c = self.cfg
        GX, GY = self.GX, self.GY
        w_dps = c.w_dps if w_dps is None else w_dps
        sig0 = c.sigma0 if sigma0 is None else sigma0
        sx, sy = self.start_after(ship, prev_target, t0)
        H, Wd = GX.shape
        i0 = int(np.clip(round((sy - c.y_range[0]) / c.gy_step), 0, H - 1))
        j0 = int(np.clip(round((sx - c.x_range[0]) / c.gx_step), 0, Wd - 1))
        n = int(c.horizon / c.dt)
        aim = self.aim_cost(enemies, ship[1]) if (w_dps > 0 and enemies) else None
        posc = self._POSC if aim is None else self._POSC + c.dt * w_dps * aim
        if y_min is not None:
            posc = posc + c.dt * 3.0 * np.clip(y_min - GY, 0, None) / 10
        cap = min(c.clear_cap, c.safe_cap)
        V = np.full((H, Wd), -np.inf)
        V[i0, j0] = cap
        cost = np.full((H, Wd), np.inf)
        cost[i0, j0] = 0.0
        args = []
        CL = self._clear_linear(predict, n) if c.vectorized and hasattr(predict, "B") else None
        k_stay = self._K.index((0, 0)) if (0, 0) in self._K else 0
        ylo, yhi = c.y_range[0] - c.band_margin, c.y_range[1] + c.band_margin
        for k in range(1, n + 1):
            t = k * c.dt
            if t > t0:                        # antes de t0 a nave ainda segue o comando antigo
                V, cost, arg = self._shift_max(V, cost)
            else:
                arg = np.full(V.shape, k_stay, np.int32)
            if CL is not None:
                V = np.minimum(V, np.minimum(CL[k - 1], cap))
                cost = cost + posc
                args.append(arg)
                continue
            P = predict(t)
            P0 = predict(t - c.dt)
            rad = getattr(predict, "rad", None)      # raio extra por ponto (naves são maiores que balas)
            if isinstance(P, tuple):                 # (ids, pos): alinha os mesmos projéteis nos dois instantes
                (i1, P), (i0_, Q0) = P, P0
                m = {key: idx for idx, key in enumerate(i0_)}
                P0 = np.array([Q0[m[key]] if key in m else p for key, p in zip(i1, P)], float).reshape(-1, 2)
                rad = None
            if rad is None or len(rad) != len(P):
                rad = np.zeros(len(P))
            xsv = getattr(predict, "xsv", None)      # incerteza extra por ponto (px/s)
            if xsv is not None and len(xsv) == len(P) and np.any(xsv):
                rad = rad + xsv * t
            if len(P0) != len(P):
                P0 = P
            if len(P):
                keep = (np.maximum(P[:, 1], P0[:, 1]) > ylo) & (np.minimum(P[:, 1], P0[:, 1]) < yhi)
                P, P0, rad = P[keep], P0[keep], rad[keep]
            if len(P):
                # distância ao SEGMENTO percorrido no passo (projétil rápido "pularia" a nave entre duas checagens)
                P = P.astype(np.float32)
                P0 = P0.astype(np.float32)
                D = P - P0
                C = self._C
                ax = C[:, 0:1] - P0[None, :, 0]
                ay = C[:, 1:2] - P0[None, :, 1]
                u = np.clip((ax * D[None, :, 0] + ay * D[None, :, 1]) / ((D ** 2).sum(1)[None] + 1e-6), 0.0, 1.0)
                rx = ax - u * D[None, :, 0]
                ry = ay - u * D[None, :, 1]
                if rad.any():
                    d = (np.sqrt(rx * rx + ry * ry) - rad[None, :].astype(np.float32)).min(1).reshape(H, Wd)
                else:
                    d = np.sqrt((rx * rx + ry * ry).min(1)).reshape(H, Wd)
                clear = np.minimum(d - (sig0 + c.sigma_v * t), cap)
            else:
                clear = np.full((H, Wd), cap)
            V = np.minimum(V, clear)
            cost = cost + posc
            args.append(arg)
        score = np.floor(V / c.quant) * 1000.0 - cost
        if prev_end is not None:
            score -= 0.02 * np.hypot(GX - prev_end[0], GY - prev_end[1])
        iy, ix = np.unravel_index(int(np.argmax(score)), score.shape)
        best = float(V[iy, ix])
        path = [(n * c.dt, float(GX[iy, ix]), float(GY[iy, ix]))]
        for k in range(n - 1, -1, -1):
            dy, dx = self._K[args[k][iy, ix]]
            iy, ix = iy - dy, ix - dx
            path.append((k * c.dt, float(GX[iy, ix]), float(GY[iy, ix])))
        path.reverse()
        tgt_t = t0 + c.lead
        tgt = min(path, key=lambda p: abs(p[0] - tgt_t))
        return (tgt[1], tgt[2]), best, path

    def _clear_linear(self, predict, n):
        """Folga (n, H, W) de todos os passos de uma vez para a previsão linear (mesma conta do laço)."""
        c = self.cfg
        H, Wd = self.GX.shape
        B = predict.B.astype(np.float32)
        rad = predict.rad
        ts = (np.arange(1, n + 1) * c.dt).astype(np.float32)
        out = np.full((n, H, Wd), c.clear_cap, np.float32)
        if not len(B):
            return out
        P0 = B[None, :, :2] + B[None, :, 2:4] * (ts - c.dt)[:, None, None]
        D = B[:, 2:4] * c.dt
        y_lo = np.minimum(P0[..., 1], P0[..., 1] + D[None, :, 1])
        y_hi = np.maximum(P0[..., 1], P0[..., 1] + D[None, :, 1])
        band = (y_hi > c.y_range[0] - c.band_margin) & (y_lo < c.y_range[1] + c.band_margin)
        ks = np.nonzero(band.any(1))[0]
        if not len(ks):
            return out
        cols = np.nonzero(band[ks].any(0))[0]
        P0 = P0[ks][:, cols]
        D = D[cols]
        band = band[ks][:, cols]
        dd = (D ** 2).sum(1) + 1e-6
        C = self._C
        ax = C[None, :, 0:1] - P0[:, None, :, 0]
        ay = C[None, :, 1:2] - P0[:, None, :, 1]
        u = np.clip((ax * D[None, None, :, 0] + ay * D[None, None, :, 1]) / dd[None, None, :], 0.0, 1.0)
        rx = ax - u * D[None, None, :, 0]
        ry = ay - u * D[None, None, :, 1]
        d2 = rx * rx + ry * ry
        d2 = np.where(band[:, None, :], d2, np.float32(1e12))
        if rad is not None and len(rad) == len(B) and np.any(rad[cols]):
            d = (np.sqrt(d2) - rad[cols][None, None, :].astype(np.float32)).min(2)
        else:
            d = np.sqrt(d2.min(2))
        sig = (c.sigma0 + c.sigma_v * ts[ks]).astype(np.float32)
        out[ks] = np.minimum(d - sig[:, None], c.clear_cap).reshape(len(ks), H, Wd)
        return out


def linear_predictor(bullets, rad=None, xsv=None):
    """bullets [(x, y, vx, vy)] -> predict(t) em linha reta.
    rad: raio extra por ponto (ou None); xsv: incerteza extra por ponto em px/s."""
    B = np.asarray(bullets, float).reshape(-1, 4)

    def predict(t):
        return B[:, :2] + B[:, 2:4] * t
    predict.B = B
    predict.rad = None if rad is None else np.asarray(rad, float)
    predict.xsv = None if xsv is None else np.asarray(xsv, float)
    return predict


def young_xsv(n_total, ages, young_age=2, young_sv=0.0):
    """Incerteza extra (px/s) para projéteis vistos poucas vezes (velocidade ainda mal medida)."""
    if young_sv <= 0 or not ages:
        return None
    x = np.zeros(n_total)
    for i, a in enumerate(ages[:n_total]):
        if a <= young_age:
            x[i] = young_sv
    return x
