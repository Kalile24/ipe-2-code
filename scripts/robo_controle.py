"""Combos do controle físico para operar o robô sem terminal (programa SEM ROS: lê o controle pelo SDK).

    F2 + UP     sobe a rotina armada (scripts/robo_rotina_cumprimento.sh --controle): só com o robô
                já em equilíbrio (FSM 801), reações automáticas desligadas
    F2 + RIGHT  cumprimenta agora a pessoa do mapa que está sendo reconhecida
    F2 + LEFT   liga/desliga as reações automáticas (o robô fala o estado)
    F2 + DOWN   para: velocidade zero na hora, braços de volta, encerra a rotina (Ctrl+C no tmux)

O controle chega no `wireless_remote` do `rt/lf/lowstate` (não no `rt/wirelesscontroller`, onde o
~/hhhh injeta toques virtuais). Uso, no robô (sobe no boot pelo scripts/systemd/ipe-controle.service):
    source ~/ipe-2-code/scripts/ambiente_robo.sh && python3 ~/ipe-2-code/scripts/robo_controle.py
    ... --mostrar      imprime os botões em hexa a cada mudança (confirmar os bits no robô)
Spec: docs/superpowers/specs/2026-11-04-aproximacao-e-estagios-design.md
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from core.remote_combos import AGORA, AUTOMATICO, INICIAR, PADRAO, PARAR, Combos, botoes  # noqa: E402

SESSAO = "rotina"  # a sessão tmux do robo_rotina_cumprimento.sh


def log(texto: str) -> None:
    print(texto, flush=True)


def sessao_de_pe() -> bool:
    return subprocess.run(["tmux", "has-session", "-t", SESSAO], capture_output=True).returncode == 0


def iniciar() -> None:
    if sessao_de_pe():
        log("F2+UP: a rotina já está de pé; nada a fazer")
        return
    log("F2+UP: subindo a rotina armada (--controle)")
    subprocess.Popen([os.path.join(REPO, "scripts", "robo_rotina_cumprimento.sh"), "--controle"])


def param_reacao(*args: str) -> str:
    saida = subprocess.run(["ros2", "param", *args], capture_output=True, text=True, timeout=20)
    return (saida.stdout + saida.stderr).strip()


def agora() -> None:
    log(f"F2+RIGHT: cumprimentar agora → {param_reacao('set', '/reaction_node', 'cumprimentar_agora', 'agora')}")


def alternar_automatico() -> None:
    ligado = "True" in param_reacao("get", "/reaction_node", "automatico")
    log(f"F2+LEFT: automático {'ligado → desligando' if ligado else 'desligado → ligando'}")
    log(param_reacao("set", "/reaction_node", "automatico", "false" if ligado else "true"))


def parar() -> None:
    if not sessao_de_pe():
        log("F2+DOWN: nenhuma rotina de pé")
        return
    log("F2+DOWN: parando (Ctrl+C na janela rotina)")
    subprocess.run(["tmux", "send-keys", "-t", f"{SESSAO}:rotina", "C-c"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for nome in (INICIAR, AGORA, AUTOMATICO, PARAR):
        parser.add_argument(f"--{nome}", type=lambda v: int(v, 0), default=PADRAO[nome], help=f"máscara (padrão {PADRAO[nome]:#06x})")
    parser.add_argument("--mostrar", action="store_true", help="imprime os botões em hexa a cada mudança")
    parser.add_argument("--interface", default="eth0")
    args = parser.parse_args()

    from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
    from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_

    acoes = {INICIAR: iniciar, AGORA: agora, AUTOMATICO: alternar_automatico, PARAR: parar}
    combos = Combos({nome: getattr(args, nome) for nome in acoes})
    ocupado = threading.Lock()  # uma ação por vez; PARAR passa sempre
    ultimo = [None]

    def rodar(nome: str) -> None:
        try:
            acoes[nome]()
        except Exception as exc:  # um ros2/tmux que falhou não derruba o programa
            log(f"{nome}: falhou: {exc!r}")
        finally:
            if nome != PARAR:
                ocupado.release()

    def ao_receber(msg: LowState_) -> None:
        keys = botoes(msg.wireless_remote)
        if args.mostrar and keys != ultimo[0]:
            log(f"botões: {keys:#06x}")
        ultimo[0] = keys
        nome = combos.update(keys)
        if nome is None:
            return
        if nome != PARAR and not ocupado.acquire(blocking=False):
            log(f"{nome}: ignorado, outra ação ainda em andamento")
            return
        threading.Thread(target=rodar, args=(nome,), daemon=True).start()  # nada lento no callback do SDK

    ChannelFactoryInitialize(0, args.interface)
    assinatura = ChannelSubscriber("rt/lf/lowstate", LowState_)
    assinatura.Init(ao_receber, 10)
    log(f"esperando combos no controle ({', '.join(f'{n}={getattr(args, n):#06x}' for n in acoes)})")
    threading.Event().wait()  # só os callbacks trabalham
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
