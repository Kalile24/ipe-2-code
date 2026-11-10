"""Mede a odometria do G1 (só leitura: NÃO envia nenhum comando ao robô).

Lê rt/odommodestate (500 Hz; o rt/lf/odommodestate de 20 Hz não publica neste G1. SportModeState_: posição x, y em metros no referencial do mundo, e yaw).
Ande com o robô pelo controle da Unitree ~1 m para a frente e volte ao mesmo lugar. Confira:
  - "andou" chega perto da distância real (0,9 a 1,1 m para 1 m);
  - de volta ao ponto, "do inicio" fica abaixo de ~0,15 m;
  - parado, "do inicio" não deriva.
Imprime ~5 Hz. Ctrl+C para sair (mostra o resumo).
"""
from __future__ import annotations

import argparse
import math
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--interface", default="eth0", help="interface de rede do robô (padrão eth0)")
    parser.add_argument("--topico", default="rt/odommodestate", help="o de 20 Hz (rt/lf/...) não publica neste G1")
    args = parser.parse_args()

    from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
    from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_

    ultimo = [None, 0]  # (x, y, yaw) e quantas mensagens chegaram

    def receber(msg: SportModeState_) -> None:
        ultimo[0] = (float(msg.position[0]), float(msg.position[1]), float(msg.imu_state.rpy[2]))
        ultimo[1] += 1

    ChannelFactoryInitialize(0, args.interface)
    sub = ChannelSubscriber(args.topico, SportModeState_)
    sub.Init(receber, 10)

    inicio, anterior, andou, maximo = None, None, 0.0, 0.0
    t0 = time.monotonic()
    try:
        while True:
            time.sleep(0.2)
            atual = ultimo[0]
            if atual is None:
                print(f"sem mensagens em {args.topico} ainda ({time.monotonic() - t0:.0f} s)...", flush=True)
                continue
            x, y, yaw = atual
            if inicio is None:
                inicio = atual
            if anterior is not None:
                andou += math.hypot(x - anterior[0], y - anterior[1])
            anterior = atual
            do_inicio = math.hypot(x - inicio[0], y - inicio[1])
            maximo = max(maximo, do_inicio)
            print(f"x {x:7.3f}  y {y:7.3f}  yaw {math.degrees(yaw):7.1f}°   do inicio {do_inicio:5.2f} m   "
                  f"andou {andou:5.2f} m   ({ultimo[1]} msgs)", flush=True)
    except KeyboardInterrupt:
        if inicio is not None:
            print(f"\nresumo: mais longe do inicio {maximo:.2f} m, andou {andou:.2f} m no total, "
                  f"terminou a {do_inicio:.2f} m do inicio", flush=True)
        return 0


if __name__ == "__main__":
    sys.exit(main())
