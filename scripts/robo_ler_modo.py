"""Mostra o modo de controle do G1 (só leitura: só PERGUNTA o modo, NÃO envia nenhum comando).

Para o teste de marcha (docs/guides/testar-marcha.md): troque o modo pelo controle da Unitree e veja aqui
qual FSM_ID ele virou. Imprime a cada 1 s e destaca as mudanças. Ctrl+C para sair.

    801  Run Control (R2+A) — o que a nossa rotina exige para armar
    500  Walk Motion (provavelmente R1+X)      501  Walk Motion, cintura de 3 eixos (provavelmente R1+Y)
    0 sem torque · 1 damping · 2 agachado · 3 sentado · 4 travado em pé · 702 deitar/levantar · 706 agachar
FSM_MODE: 0 parado em pé, 1 andando.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

NOMES = {0: "sem torque", 1: "damping", 2: "agachado", 3: "sentado", 4: "travado em pé", 500: "Walk (500)",
         501: "Walk cintura 3 eixos (501)", 702: "deitar/levantar", 706: "agachar/levantar", 801: "Run Control (801)",
         802: "Run Control (802)"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--interface", default="eth0")
    args = parser.parse_args()

    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    from unitree_sdk2py.g1.loco.g1_loco_api import ROBOT_API_ID_LOCO_GET_FSM_ID, ROBOT_API_ID_LOCO_GET_FSM_MODE
    from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient

    ChannelFactoryInitialize(0, args.interface)
    loco = LocoClient()
    loco.SetTimeout(3.0)
    loco.Init()

    def ler(api_id: int) -> object:  # GetFsmId/GetFsmMode: consultas, não mudam nada no robô
        codigo, dados = loco._Call(api_id, "{}")
        try:
            return json.loads(dados)["data"] if codigo == 0 and dados else None
        except (KeyError, TypeError, ValueError):
            return None

    anterior = None
    try:
        while True:
            fsm_id, fsm_mode = ler(ROBOT_API_ID_LOCO_GET_FSM_ID), ler(ROBOT_API_ID_LOCO_GET_FSM_MODE)
            texto = f"FSM_ID={fsm_id} ({NOMES.get(fsm_id, '?')})  FSM_MODE={fsm_mode} ({ {0: 'parado', 1: 'andando'}.get(fsm_mode, '?') })"
            marca = "   <== MUDOU" if anterior is not None and fsm_id != anterior else ""
            print(time.strftime("%H:%M:%S"), texto + marca, flush=True)
            anterior = fsm_id
            time.sleep(1.0)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
