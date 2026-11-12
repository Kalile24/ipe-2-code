"""Combos do controle físico para operar o robô sem terminal (programa SEM ROS: lê o controle pelo SDK).

    F2 + UP     sobe a rotina armada (scripts/robo_rotina_cumprimento.sh --controle): só com o robô
                já em equilíbrio (FSM 801), reações automáticas desligadas
    F2 + RIGHT  cumprimenta agora a pessoa do mapa que está sendo reconhecida
    F2 + LEFT   liga/desliga as reações automáticas (o robô fala o estado)
    F2 + DOWN   para: velocidade zero na hora, braços de volta, encerra a rotina (Ctrl+C no tmux)
    F2 + B      SEGURADO 1,5 s: damp (motores soltos). SÓ NO SUPORTE: fora dele o robô cai.
                Recusado com a rotina de pé (F2+DOWN antes). O L2+B da Unitree não faz damp no 801.
    F2 + A      SEGURADO 1,5 s: levanta no suporte (damp → em pé → equilíbrio, scripts/robo_levantar.py);
                só com o robô mole (damp/sem torque)
    F2 + X      a vontade: solta a posição mantida por um comando de voz (sentido, continência, descansar)
    F2 + L1     liga/desliga a escuta contínua de voz (só frases com "Tenente ..."); bipes e fala avisam
    F2 + R1     fala de apresentação: sentido, o texto de data/discurso.txt (o painel edita) e à vontade
    F2 + Y      SEGURADO: fala (o microfone grava enquanto apertado; ao soltar, o comando é reconhecido)

O controle chega no `wireless_remote` do `rt/lf/lowstate` (não no `rt/wirelesscontroller`, onde o
~/hhhh injeta toques virtuais). Uso, no robô (sobe no boot pelo scripts/systemd/ipe-controle.service):
    source ~/ipe-2-code/scripts/ambiente_robo.sh && python3 ~/ipe-2-code/scripts/robo_controle.py
    ... --mostrar      imprime os botões em hexa a cada mudança (confirmar os bits no robô)
Spec: docs/superpowers/specs/2026-11-04-aproximacao-e-estagios-design.md
"""
from __future__ import annotations

import argparse
import fcntl
import os
import subprocess
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from core.bipes import tocar  # noqa: E402
from core.remote_combos import (  # noqa: E402
    A_VONTADE, AGORA, AUTOMATICO, DAMP, DISCURSO, ESCUTA, FALAR, FIM, INICIAR, LEVANTAR, PADRAO, PARAR, SEGURAR, SEGURAR_S, Combos,
    Segurado, botoes, segue_apertado,
)
from core import bateria  # noqa: E402
from core.comandos_voz import enviar_voz  # noqa: E402

SESSAO = "rotina"  # a sessão tmux do robo_rotina_cumprimento.sh
# A mesma trava do robo_rotina_cumprimento.sh: presa enquanto uma subida está em andamento.
TRAVA_SUBIDA = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "ipe-rotina-subida.lock")
ESPERA_ENCERRAR_S = 90.0  # o body_node devolve os braços antes de sair (até ~60 s no pior caso)
LEVANTAR_TIMEOUT_S = 120.0
LEVANTANDO: subprocess.Popen | None = None  # o robo_levantar.py em andamento: o F2+DOWN pode abortá-lo


def log(texto: str) -> None:
    print(texto, flush=True)


def sessao_de_pe() -> bool:
    return subprocess.run(["tmux", "has-session", "-t", SESSAO], capture_output=True).returncode == 0


def subida_em_andamento() -> bool:
    try:
        with open(TRAVA_SUBIDA, "a") as arquivo:
            fcntl.flock(arquivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(arquivo, fcntl.LOCK_UN)
            return False
    except BlockingIOError:
        return True


def rotina_rodando() -> bool:
    """A janela 'rotina' ainda está no ros2 launch (e não de volta no bash)."""
    saida = subprocess.run(["tmux", "display-message", "-p", "-t", f"{SESSAO}:rotina", "#{pane_current_command}"],
                           capture_output=True, text=True)
    return saida.returncode == 0 and saida.stdout.strip() not in ("bash", "sh", "")


def iniciar() -> None:
    soc = bateria.ler()
    if not bateria.pode_armar(soc):
        log(f"F2+UP: recusado, bateria em {soc}% (mínimo {bateria.MINIMO}%): troque a bateria")
        tocar("recusado")
        return
    if sessao_de_pe() or subida_em_andamento():
        log("F2+UP: a rotina já está de pé (ou subindo); nada a fazer")
        tocar("recusado")
        return
    log("F2+UP: subindo a rotina armada (--controle)")
    tocar("iniciar")
    subprocess.Popen([os.path.join(REPO, "scripts", "robo_rotina_cumprimento.sh"), "--controle"])


def param_reacao(*args: str) -> str:
    saida = subprocess.run(["ros2", "param", *args], capture_output=True, text=True, timeout=20)
    return (saida.stdout + saida.stderr).strip()


def agora() -> None:
    resposta = param_reacao("set", "/reaction_node", "cumprimentar_agora", "agora")
    tocar("agora" if "successful" in resposta else "recusado")
    log(f"F2+RIGHT: cumprimentar agora → {resposta}")


def alternar_automatico() -> None:
    ligado = "True" in param_reacao("get", "/reaction_node", "automatico")
    log(f"F2+LEFT: automático {'ligado → desligando' if ligado else 'desligado → ligando'}")
    resposta = param_reacao("set", "/reaction_node", "automatico", "false" if ligado else "true")
    tocar("automatico" if "successful" in resposta else "recusado")
    log(resposta)


PARANDO = threading.Lock()  # vários F2+DOWN seguidos: um só espera e fecha a sessão


def parar() -> None:
    if not PARANDO.acquire(blocking=False):
        log("F2+DOWN: já parando")
        return
    try:
        _parar()
    finally:
        PARANDO.release()


def _parar() -> None:
    levantando = LEVANTANDO
    if levantando is not None and levantando.poll() is None:
        # Aborta a sequência onde estiver (o robô está no suporte); depois o F2+B segurado dá damp.
        log("F2+DOWN: abortando o levantar")
        levantando.terminate()
        tocar("parar")
        return
    if not sessao_de_pe():
        log("F2+DOWN: nenhuma rotina de pé")
        tocar("recusado")
        return
    log("F2+DOWN: parando (Ctrl+C na janela rotina)")
    subprocess.run(["tmux", "send-keys", "-t", f"{SESSAO}:rotina", "C-c"])  # antes do bipe: parar vem primeiro
    tocar("parar")
    # Só fecha a sessão depois que o launch saiu (braços devolvidos): fechar no meio mataria o
    # body_worker com o arm_sdk ativo. Sem fechar, o próximo F2+UP dizia "já está de pé".
    fim = time.monotonic() + ESPERA_ENCERRAR_S
    while rotina_rodando() and time.monotonic() < fim:
        time.sleep(0.5)
    if rotina_rodando():
        log("F2+DOWN: a rotina não terminou em 90 s; sessão mantida (veja tmux attach -t rotina)")
        tocar("recusado")
        return
    subprocess.run(["tmux", "kill-session", "-t", SESSAO])
    log("F2+DOWN: rotina encerrada; F2+UP sobe de novo")
    tocar("encerrada")


def corpo_ocupado() -> bool:
    """A rotina (ou outro dono do corpo) está de pé: damp/levantar não podem disputar com ela."""
    worker = subprocess.run(["pgrep", "-f", "robot_reaction_ros.body_worker"], capture_output=True).returncode == 0
    return sessao_de_pe() or subida_em_andamento() or worker


def damp() -> None:
    if corpo_ocupado():
        log("F2+B: recusado, a rotina está de pé (F2+DOWN antes)")
        tocar("recusado")
        return
    log("F2+B: DAMP (motores soltos)")
    tocar("damp")
    saida = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "robo_emergencia.py"), "--agora"],
                           capture_output=True, text=True, timeout=30)
    log(saida.stdout.strip())
    if saida.returncode != 0:
        tocar("recusado")


def levantar() -> None:
    global LEVANTANDO
    if corpo_ocupado():
        log("F2+A: recusado, a rotina está de pé")
        tocar("recusado")
        return
    log("F2+A: levantando (damp → em pé → equilíbrio)")
    tocar("iniciar")
    LEVANTANDO = subprocess.Popen([sys.executable, os.path.join(REPO, "scripts", "robo_levantar.py")],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        stdout, _ = LEVANTANDO.communicate(timeout=LEVANTAR_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        LEVANTANDO.kill()
        stdout, _ = LEVANTANDO.communicate()
    linhas = [l for l in stdout.splitlines() if l.startswith("levantar:")]
    log("\n".join(linhas) or stdout.strip()[-300:])
    tocar("encerrada" if LEVANTANDO.returncode == 0 else "recusado")
    LEVANTANDO = None


def a_vontade() -> None:
    log("F2+X: a vontade (solta a posição mantida)")
    enviar_voz("comando:a_vontade")


def escuta() -> None:
    log("F2+L1: liga/desliga a escuta contínua")
    enviar_voz("escuta:alternar")  # o nó de voz toca os bipes e fala o estado


def discurso() -> None:
    log("F2+R1: fala de apresentação")
    enviar_voz("comando:discurso")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for nome in (INICIAR, AGORA, AUTOMATICO, PARAR, DAMP, LEVANTAR, A_VONTADE, DISCURSO, ESCUTA):
        parser.add_argument(f"--{nome}", type=lambda v: int(v, 0), default=PADRAO[nome], help=f"máscara (padrão {PADRAO[nome]:#06x})")
    parser.add_argument("--falar", type=lambda v: int(v, 0), default=FALAR, help=f"máscara de falar, segurado (padrão {FALAR:#06x})")
    parser.add_argument("--mostrar", action="store_true", help="imprime os botões em hexa a cada mudança")
    parser.add_argument("--interface", default="eth0")
    args = parser.parse_args()

    from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
    from unitree_sdk2py.idl.unitree_hg.msg.dds_ import BmsState_, LowState_

    acoes = {INICIAR: iniciar, AGORA: agora, AUTOMATICO: alternar_automatico, PARAR: parar, DAMP: damp,
             LEVANTAR: levantar, A_VONTADE: a_vontade, DISCURSO: discurso, ESCUTA: escuta}
    combos = Combos({nome: getattr(args, nome) for nome in acoes})
    falar = Segurado(args.falar)
    ocupado = threading.Lock()  # uma ação por vez; PARAR passa sempre
    ultimo = [None]
    recebido_em = [0.0]

    def rodar(nome: str) -> None:
        try:
            if nome in SEGURAR:
                # Aviso já; só executa se o combo continuar apertado o tempo todo.
                tocar("segurar")
                mascara = getattr(args, nome)
                fim = time.monotonic() + SEGURAR_S
                while time.monotonic() < fim:
                    if not segue_apertado(ultimo[0], mascara, recebido_em[0], time.monotonic()):
                        log(f"{nome}: soltou (ou o controle parou de chegar) antes de {SEGURAR_S} s; cancelado")
                        return
                    time.sleep(0.05)
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
        ultimo[0], recebido_em[0] = keys, time.monotonic()
        aviso = falar.update(keys)  # direto no callback: sem o lock `ocupado`, nada bloqueia
        if aviso is not None:
            enviar_voz("falar_fim" if aviso == FIM else "falar_inicio")
        nome = combos.update(keys)
        if nome is None:
            return
        if nome != PARAR and not ocupado.acquire(blocking=False):
            log(f"{nome}: ignorado, outra ação ainda em andamento")
            return
        threading.Thread(target=rodar, args=(nome,), daemon=True).start()  # nada lento no callback do SDK

    bat = {"gravado_em": 0.0, "nivel": "ok"}

    def ao_receber_bateria(msg: BmsState_) -> None:
        # Grava a carga para o painel e para a subida armada; avisa (bipe e log) ao cair de nível.
        agora = time.monotonic()
        if agora - bat["gravado_em"] < 5.0:
            return
        bat["gravado_em"] = agora
        soc = int(msg.soc)
        try:
            bateria.gravar(soc)
        except OSError as exc:
            log(f"bateria: não gravei a carga: {exc!r}")
        nivel = bateria.nivel(soc)
        if nivel != bat["nivel"] and nivel in ("baixa", "critica"):
            log(f"bateria {nivel}: {soc}%" + (" — troque antes de armar" if nivel == "critica" else ""))
            tocar("recusado")
        bat["nivel"] = nivel

    ChannelFactoryInitialize(0, args.interface)
    assinatura = ChannelSubscriber("rt/lf/lowstate", LowState_)
    assinatura.Init(ao_receber, 10)
    assinatura_bateria = ChannelSubscriber("rt/lf/bmsstate", BmsState_)
    assinatura_bateria.Init(ao_receber_bateria, 1)
    log(f"esperando combos no controle ({', '.join(f'{n}={getattr(args, n):#06x}' for n in acoes)})")
    threading.Event().wait()  # só os callbacks trabalham
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
