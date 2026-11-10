"""Testes do core (sem jogo, sem celular):  python -m unittest discover -s tests -v"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shooter_core import (PlannerConfig, SpaceTimePlanner, Tracker, RelativePilot, PilotConfig, ShipEstimator,
                          linear_predictor, for_screen)
from shooter_core.sim import run_episode


class PlannerTest(unittest.TestCase):
    def setUp(self):
        self.p = SpaceTimePlanner(PlannerConfig())

    def test_atravessa_muro_pelo_vao(self):
        wall = [(x, 1300, 0, 900) for x in range(40, 1080, 90) if not 600 <= x <= 840]
        tgt, clear, path = self.p.plan((300, 2000), linear_predictor(wall), t0=0.15)
        xs = [x for t, x, y in path if 0.7 <= t <= 0.9]
        self.assertGreater(clear, 0)
        self.assertTrue(all(560 <= x <= 880 for x in xs), xs)

    def test_sem_balas_fica_no_lugar(self):
        self.p.cfg.w_dps = 0.0
        tgt, clear, path = self.p.plan((540, 2000), linear_predictor([]), t0=0.15)
        self.assertLessEqual(abs(tgt[0] - 540), 30)
        self.assertLessEqual(abs(tgt[1] - 2000), 40)

    def test_ofensiva_vai_para_baixo_do_inimigo(self):
        enemy = [(550.0, 600.0, 60.0)]          # perto: compensa andar até a coluna dele
        ship, tgt = (300.0, 2000.0), None
        for _ in range(20):                    # horizonte deslizante: vários planos seguidos
            tgt, _, path = self.p.plan(ship, linear_predictor([]), t0=0.15, prev_target=tgt, enemies=enemy)
            ship = tgt
        self.assertLess(abs(ship[0] - 550), self.p.cfg.aim_w, ship)

    def test_sem_ofensiva_ignora_inimigo(self):
        tgt, _, _ = self.p.plan((300.0, 2000.0), linear_predictor([]), t0=0.15, enemies=[(550.0, 600.0)], w_dps=0.0)
        self.assertLess(tgt[0], 360)

    def test_y_min_empurra_para_baixo(self):
        tgt, _, path = self.p.plan((540.0, 1700.0), linear_predictor([]), t0=0.0, y_min=1900.0)
        self.assertGreater(path[-1][2], 1850)

    def test_bala_em_cima_foge(self):
        b = [(540.0, 1700.0, 0.0, 900.0)]       # vem direto na nave
        tgt, clear, path = self.p.plan((540.0, 2000.0), linear_predictor(b), t0=0.1)
        self.assertGreater(abs(path[-1][1] - 540), 60)

    def test_vetorizado_igual_ao_laco(self):
        b = [(x, 1500 + 37 * (x % 7), (x % 5) * 20 - 40, 800.0) for x in range(80, 1000, 70)]
        a = self.p.plan((400.0, 2000.0), linear_predictor(b), t0=0.15)
        self.p.cfg.vectorized = True
        v = self.p.plan((400.0, 2000.0), linear_predictor(b), t0=0.15)
        self.assertEqual(a[0], v[0])


class TrackerTest(unittest.TestCase):
    def test_velocidade_constante(self):
        tr = Tracker()
        prev, dt = [], 0.05
        for k in range(8):
            cur = [(300 + 100 * k * dt, 500 + 900 * k * dt), (800, 400 + 600 * k * dt)]
            prev = tr.update(prev, cur, dt if k else 0)
        (x, y, vx, vy), (_, _, vx2, vy2) = prev
        self.assertAlmostEqual(vx, 100, delta=5)
        self.assertAlmostEqual(vy, 900, delta=10)
        self.assertAlmostEqual(vy2, 600, delta=10)
        self.assertEqual(tr.ages_of(prev), [7, 7])   # o 1º quadro (dt = 0) não tem histórico

    def test_memoria_de_bala_que_some(self):
        tr = Tracker()
        prev = [(500.0, 1800.0, 0.0, 900.0)]
        kept = tr.coast(prev, [], [], 0.05, ship=(500.0, 1900.0))
        self.assertEqual(len(kept), 1)
        self.assertAlmostEqual(kept[0][1], 1845.0)
        far = tr.coast(prev, [], [], 0.05, ship=(100.0, 2200.0))
        self.assertEqual(far, [])                 # longe da nave: não lembra

    def test_inimigo_descendo_vira_obstaculo(self):
        tr = Tracker()
        pts = tr.enemy_points([(500.0, 1500.0, 0.0, 200.0), (900.0, 1500.0, 0.0, 0.0)], ship=(500.0, 2000.0))
        self.assertEqual(len(pts), 3)             # só o que desce; corpo em 3 pontos
        self.assertEqual(tr.enemy_points([(500.0, 1990.0, 0.0, 200.0)], ship=(500.0, 2000.0)), [])  # a própria nave


class FakeTouch:
    def __init__(self):
        self.ev = []

    def touch_down(self, x, y): self.ev.append(("d", x, y))
    def touch_move(self, x, y): self.ev.append(("m", x, y))
    def touch_up(self, x, y): self.ev.append(("u", x, y))


class PilotTest(unittest.TestCase):
    def test_passos_pequenos_e_borda(self):
        dev, t = FakeTouch(), [0.0]
        p = RelativePilot(dev, PilotConfig(), threaded=False, clock=lambda: t[0])
        p.steer((540.0, 2000.0), (1040.0, 2000.0), frame_time=0.0)    # 500 px para a direita
        for _ in range(200):
            t[0] += 1 / 60
            p.tick()
        steps = [math.hypot(b[1] - a[1], b[2] - a[2]) for a, b in zip(dev.ev, dev.ev[1:])
                 if a[0] == b[0] == "m"]                                  # entre recolocações do dedo
        self.assertTrue(all(s <= p.cfg.step + 1e-6 for s in steps))
        self.assertIn("u", [e[0] for e in dev.ev])                     # recolocou o dedo na borda
        self.assertAlmostEqual(p.virt[0] * p.cfg.gain, 500.0, delta=1)  # a nave andou o pedido

    def test_zona_morta(self):
        dev = FakeTouch()
        p = RelativePilot(dev, PilotConfig(), threaded=False)
        p.steer((540.0, 2000.0), (550.0, 2005.0), frame_time=0.0)
        p.tick(); p.tick()
        self.assertEqual([e[0] for e in dev.ev], ["d"])               # encosta, mas não mexe


class ShipTest(unittest.TestCase):
    def test_salto_impossivel_e_estimativa(self):
        est = ShipEstimator(predict=lambda s, t0, t1: (s[0] + 100 * (t1 - t0), s[1]))
        self.assertTrue(est.update((500.0, 2000.0), 1.0).detected)
        st = est.update((100.0, 1400.0), 1.05)                         # pulou 700 px em 50 ms
        self.assertFalse(st.detected)
        self.assertAlmostEqual(st.pos[0], 505.0)                       # estimada pelo controle
        self.assertTrue(est.update(None, 2.0).lost)                    # sumiu por muito tempo


class ConfigTest(unittest.TestCase):
    def test_for_screen_escala(self):
        c = for_screen(540, 1170)
        self.assertEqual(c.planner.width, 540)
        self.assertAlmostEqual(c.planner.y_range[1], 1075.0)
        self.assertAlmostEqual(c.pilot.step, 9.0)
        SpaceTimePlanner(c.planner)                                    # a grade monta


class ArenaTest(unittest.TestCase):
    """O core inteiro (visão do adaptador -> rastreio -> plano -> piloto com latência) na arena sintética."""

    def test_bot_leva_menos_tiro_e_mata_mais(self):
        idle = run_episode(20, "idle", seed=5)
        bot = run_episode(20, "bot", seed=5)
        self.assertLess(bot["hits"], 0.5 * idle["hits"], (bot, idle))
        self.assertGreaterEqual(bot["kills"], idle["kills"], (bot, idle))

    def test_ofensiva_aumenta_tempo_na_mira(self):
        on = run_episode(15, "bot", seed=2)
        off = run_episode(15, "bot", seed=2, offense=False)
        self.assertGreater(on["aligned_pct"], off["aligned_pct"], (on, off))


if __name__ == "__main__":
    unittest.main()
