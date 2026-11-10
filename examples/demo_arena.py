"""Demonstração: o core jogando a arena sintética, numa janela.

    python examples/demo_arena.py                 # bot jogando (Esc fecha)
    python examples/demo_arena.py --parado        # nave parada, para comparar
    python examples/demo_arena.py --sem-janela    # só as métricas (mais rápido)
    python examples/demo_arena.py --segundos 60 --dificuldade 1.5 --semente 3
"""
import argparse
import os
import sys

import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shooter_core.sim import run_episode  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--segundos", type=float, default=45)
    ap.add_argument("--semente", type=int, default=0)
    ap.add_argument("--dificuldade", type=float, default=1.0)
    ap.add_argument("--parado", action="store_true")
    ap.add_argument("--sem-ofensiva", action="store_true")
    ap.add_argument("--sem-janela", action="store_true")
    a = ap.parse_args()

    def show(arena, ctx):
        img = arena.render()
        if ctx is not None:
            for x, y, vx, vy in ctx.threats:                       # previsão de 0.3 s de cada ameaça
                cv2.line(img, (int(x), int(y)), (int(x + vx * 0.3), int(y + vy * 0.3)), (90, 90, 200), 1)
            if ctx.target:
                cv2.circle(img, (int(ctx.target[0]), int(ctx.target[1])), 10, (0, 255, 0), 2)
        cv2.putText(img, f"t {arena.t:4.1f}s  tiros levados {arena.hits}  abates {arena.kills}", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.imshow("AutoSpaceShooterCore: arena", img)
        if cv2.waitKey(1) == 27:
            raise KeyboardInterrupt

    try:
        res = run_episode(a.segundos, "idle" if a.parado else "bot", seed=a.semente, difficulty=a.dificuldade,
                          on_frame=None if a.sem_janela else show, offense=not a.sem_ofensiva)
        print(f"{res['mode']}: {res['hits']} tiros levados ({res['hits_per_min']:.1f}/min), {res['kills']} abates, "
              f"{res['aligned_pct']:.0f}% do tempo na mira, em {res['seconds']:.0f}s de jogo")
    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
