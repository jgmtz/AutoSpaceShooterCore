"""Configuração do core: tudo que muda de um jogo para outro fica aqui, nunca fixo no código.

Os valores padrão foram afinados numa tela retrato de 1080 x 2340 px (um shooter vertical de celular).
Para outra resolução use `for_screen(largura, altura)`, que escala distâncias e velocidades na mesma proporção.
"""
from dataclasses import dataclass, field, replace

REF_W, REF_H = 1080.0, 2340.0


@dataclass
class PlannerConfig:
    """Planejador espaço-tempo (shooter_core.planner)."""
    width: float = 1080.0                    # largura da área de jogo (px)
    x_range: tuple = (60.0, 1020.0)          # faixa horizontal permitida para o centro da nave
    y_range: tuple = (1650.0, 2150.0)        # faixa vertical permitida (embaixo = mais tempo para reagir)
    gx_step: float = 30.0                    # resolução da grade (px)
    gy_step: float = 40.0
    dt: float = 0.04                         # passo de tempo (s)
    horizon: float = 1.2                     # quanto à frente o plano olha (s)
    speed: float = 1000.0                    # velocidade efetiva da nave usada no plano (px/s)
    real_speed: float = 1100.0               # velocidade real (para estimar onde a nave estará em t0)
    lead: float = 0.12                       # s depois de t0: ponto do caminho usado como destino imediato
    sigma0: float = 6.0                      # incerteza da previsão no instante 0 (px)
    sigma_v: float = 60.0                    # incerteza que cresce por segundo de previsão (px/s)
    clear_cap: float = 160.0                 # folga acima disso conta como "seguro"
    quant: float = 8.0                       # folgas dentro disso são iguais (desempate pelo custo)
    band_margin: float = 150.0               # balas fora da faixa da nave +- isso são ignoradas
    prefer_x: float = None                   # posição preferida (None = centro da tela)
    prefer_y: float = 2000.0
    w_center: float = 0.15                   # peso de ficar perto de prefer_x (por 100 px, por s)
    w_low: float = 0.25                      # peso de ficar perto de prefer_y (por 100 px, por s)
    w_move: float = 0.02                     # custo por px andado
    # ofensiva: ficar na coluna de tiro de um inimigo acima da nave (armas que atiram reto para cima)
    w_dps: float = 10.0                      # 0 = só defesa
    safe_cap: float = 160.0                  # folga a partir da qual o caminho é "seguro o bastante" para mirar
    aim_w: float = 90.0                      # meia-largura da coluna de tiro (px)
    aim_min_dy: float = 150.0                # o inimigo precisa estar pelo menos isso acima da nave
    vectorized: bool = False                 # cálculo de folga todo de uma vez (mais memória, nem sempre mais rápido)

    def __post_init__(self):
        if self.prefer_x is None:
            self.prefer_x = self.width / 2


@dataclass
class TrackerConfig:
    """Rastreio de projéteis e inimigos (shooter_core.tracking)."""
    default_v: tuple = (0.0, 850.0)          # velocidade suposta de uma bala sem histórico (px/s)
    v_max: float = 1800.0                    # acima disso a medida é descartada
    max_up: float = -200.0                   # vy menor que isso (subindo rápido) é descartado
    gate_base: float = 45.0                  # portão de associação: base (px) + fração do deslocamento
    gate_k: float = 0.4
    smooth: float = 0.5                      # suavização da velocidade (0 = só a medida nova)
    lsq_n: int = 0                           # reta nas últimas N observações (0 = desligado)
    neighbor_r: float = 0.0                  # bala sem histórico herda a velocidade da vizinha (0 = desligado)
    turn_min_speed: float = 200.0            # só mede giro de balas mais rápidas que isso
    # memória de balas que somem do detector (oclusão por explosão, sobreposição com a nave)
    coast_s: float = 0.3
    coast_near: float = 260.0
    coast_vmin: float = 300.0
    # inimigos como obstáculo móvel
    enemy_obst: bool = True
    enemy_vy_min: float = 60.0
    enemy_near: float = 300.0
    enemy_half: float = 55.0
    enemy_self: float = 100.0
    enemy_above: float = 1100.0
    enemy_below: float = 60.0


@dataclass
class PilotConfig:
    """Piloto de controle RELATIVO (arrastar o dedo/mouse move a nave o mesmo tanto x gain)."""
    gain: float = 1.12                       # deslocamento da nave / deslocamento do dedo
    step: float = 18.0                       # px máximos por evento de movimento
    hz: float = 60.0
    latency: float = 0.10                    # s entre enviar o movimento e ele aparecer no quadro
    deadband: float = 30.0                   # erro menor que isso não mexe
    fx: tuple = (120.0, 960.0)               # área onde o dedo pode ficar
    fy: tuple = (700.0, 2150.0)
    home: tuple = (540.0, 1600.0)            # onde o dedo encosta / é recolocado


@dataclass
class ShipConfig:
    """Estimativa da posição da nave (shooter_core.ship)."""
    teleport_px: float = 400.0               # salto maior que isso em pouco tempo = leitura errada
    teleport_dt: float = 0.3
    jump_px: float = 90.0                    # tolerância entre a nave detectada e a prevista pelo controle
    jump_v: float = 900.0                    # tolerância extra por segundo desde a última detecção
    jump_window: float = 0.6                 # o filtro só vale se a última detecção é mais nova que isso
    trust_s: float = 0.4                     # conflito por mais que isso = volta a confiar na detecção
    hold_s: float = 0.5                      # nave sumida: estima pelo controle por até isso
    bounds: tuple = (0.0, 1080.0, 1300.0, 2340.0)   # x0, x1, y0, y1 da estimativa


@dataclass
class LoopConfig:
    """Loop genérico (shooter_core.loop)."""
    plan_t0: float = 0.15                    # s até o comando valer
    plan_async: bool = True                  # planejar numa thread enquanto o próximo quadro é processado
    idle_after: float = 1.0                  # s sem balas: vai e volta (alguns jogos desaceleram com a nave parada)
    wiggle_x: tuple = (380.0, 700.0)
    max_dt: float = 0.3                      # intervalo entre quadros acima disso zera o rastreio


@dataclass
class CoreConfig:
    planner: PlannerConfig = field(default_factory=PlannerConfig)
    tracker: TrackerConfig = field(default_factory=TrackerConfig)
    pilot: PilotConfig = field(default_factory=PilotConfig)
    ship: ShipConfig = field(default_factory=ShipConfig)
    loop: LoopConfig = field(default_factory=LoopConfig)


def _sx(t, k):
    return tuple(v * k for v in t)


def for_screen(width, height):
    """CoreConfig com os padrões escalados para uma tela width x height (retrato, nave embaixo)."""
    kx, ky = width / REF_W, height / REF_H
    k = min(kx, ky)
    base = CoreConfig()
    p = base.planner
    planner = replace(p, width=float(width), x_range=_sx(p.x_range, kx), y_range=_sx(p.y_range, ky),
                      gx_step=p.gx_step * kx, gy_step=p.gy_step * ky, speed=p.speed * k, real_speed=p.real_speed * k,
                      sigma0=p.sigma0 * k, sigma_v=p.sigma_v * k, clear_cap=p.clear_cap * k, quant=p.quant * k,
                      band_margin=p.band_margin * ky, prefer_x=width / 2, prefer_y=p.prefer_y * ky,
                      safe_cap=p.safe_cap * k, aim_w=p.aim_w * kx, aim_min_dy=p.aim_min_dy * ky)
    t = base.tracker
    tracker = replace(t, default_v=_sx(t.default_v, k), v_max=t.v_max * k, max_up=t.max_up * k,
                      gate_base=t.gate_base * k, turn_min_speed=t.turn_min_speed * k, coast_near=t.coast_near * k,
                      coast_vmin=t.coast_vmin * k, enemy_vy_min=t.enemy_vy_min * k, enemy_near=t.enemy_near * k,
                      enemy_half=t.enemy_half * kx, enemy_self=t.enemy_self * k, enemy_above=t.enemy_above * ky,
                      enemy_below=t.enemy_below * ky, neighbor_r=t.neighbor_r * k)
    pc = base.pilot
    pilot = replace(pc, step=pc.step * k, deadband=pc.deadband * k, fx=_sx(pc.fx, kx), fy=_sx(pc.fy, ky),
                    home=(pc.home[0] * kx, pc.home[1] * ky))
    s = base.ship
    ship = replace(s, teleport_px=s.teleport_px * k, jump_px=s.jump_px * k, jump_v=s.jump_v * k,
                   bounds=(0.0, float(width), s.bounds[2] * ky, float(height)))
    lp = base.loop
    loop = replace(lp, wiggle_x=_sx(lp.wiggle_x, kx))
    return CoreConfig(planner, tracker, pilot, ship, loop)
