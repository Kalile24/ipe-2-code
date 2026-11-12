"""Processo SEM ROS que fala com o robô pelo G1ArmController (g1_arm_controller.py).

Por que um processo à parte: o rclpy e o SDK da Unitree usam o CycloneDDS com configurações
diferentes, e no mesmo processo o `ChannelFactoryInitialize` falha ("channel factory init
error"; testado no robô em 2026-10-29). O body_node (ROS) abre este processo e conversa com ele
por linhas JSON: uma ordem na entrada padrão, uma resposta no stdout de protocolo.

    → {"id": 7, "cmd": "initialize"} | {"id": 8, "cmd": "posture", "nome": "sentido"} | {"id": 9, "cmd": "shutdown"}
    ← {"id": 7, "ok": true} | {"id": 8, "ok": false, "erro": "..."}

A resposta repete o `id` da ordem: se o body_node desistiu de esperar uma postura, a resposta
atrasada dela não é confundida com a da ordem seguinte.
Ao subir, ele cria o controlador e responde uma vez ({"ok": ...}, sem id) antes de qualquer ordem.
Entrada fechada (o body_node morreu) = shutdown: braços de volta ao equilíbrio.
`{"id": 7, "cmd": "initialize", "so_equilibrio": true}`: só começa se o robô já está em
equilíbrio (FSM 801), sem damp.

Andar não espera postura e não tem resposta (nem `id`):
    → {"cmd": "velocidade", "vx": 0.1, "vyaw": -0.2} | {"cmd": "parar"}

`{"id": 9, "cmd": "meia_volta", "cfg": {<campos do MeiaVoltaConfig>}}`: gira 180° para a esquerda
pela IMU e dá um passo; responde ok, ou {"ok": false, "erro": "<falha>" | "interrompida"}. É a
ordem que o `parar` interrompe (a thread de leitura aciona o evento e para o robô).
"""
from __future__ import annotations

import json
import math
import os
import queue
import signal
import sys
import threading
import time
from typing import IO

from core.meia_volta import CHEGOU, GIRANDO, MeiaVoltaConfig, acumular, duracao_passo, passo_giro

SEM_TORQUE_OU_DAMP = (0, 1)  # FSM_ID do G1 com os motores soltos: o damp não muda nada


def em_equilibrio(fsm_id: object, fsm_mode: object) -> bool:
    """FSM 801 = o controlador de equilíbrio. O MODE só diz se o arm_sdk está ativo (3, logo depois
    de outra rodada soltar os braços; o ler_estado dá tempo para ele voltar a 0) e a leitura dele
    pode falhar (None): o 801 basta. ponytail: se um worker morreu no meio de um gesto, os braços
    fora do lugar viram a "postura de equilíbrio" (ver o guia); recusar aqui impedia a operação."""
    return fsm_id == 801 and fsm_mode in (0, 3, None)


class G1Body:
    """As posturas militares, chamadas como o ~/hhhh/movimentos_militares.py chama (F1+...).

    Usa a nossa cópia do G1ArmController (g1_arm_controller.py, com as poses do pacote), com as
    mesmas velocidades do movimentos_militares.py; nada do ~/hhhh é importado. O
    movimentos_militares.py não pode estar rodando junto: seriam dois processos publicando em
    rt/arm_sdk.
    """

    def __init__(self, poses_dir: str, network_interface: str, rest_forward_pulse: bool = True) -> None:
        # As constantes das poses são lidas na importação: G1_POSE_DIR tem que vir antes.
        if poses_dir:
            os.environ["G1_POSE_DIR"] = poses_dir
        from robot_reaction_ros.g1_arm_controller import DESC_ARMA_MAX_JOINT_SPEED, G1ArmController

        self.robot = G1ArmController(iface=network_interface, kp=35.0, kd=1.2, max_joint_speed=0.35)
        # True = o Descansar dá um passo curto para frente (SetVelocity 0,12 m/s) para compensar
        # os braços indo para trás, como no ~/hhhh.
        self.robot.rest_forward_pulse = rest_forward_pulse
        time.sleep(3.0)  # mesma espera do MovimentosMilitares: DDS e LocoClient estabilizarem
        # Postura -> (velocidade máxima das juntas ou None = a da própria rotina, função).
        self._posturas = {
            "sentido": (0.7, self.robot.move_to_attention),
            "descansar": (None, self.robot.move_to_rest),
            "continencia": (2.0, self.robot.move_to_saved_salute),
            "desc_arma": (DESC_ARMA_MAX_JOINT_SPEED, self.robot.lower_salute_to_attention),
            "a_vontade": (None, self.robot.return_to_balance_and_release),
        }

    # Cada leitura que o robô não responde espera 5 s por RPC (ID e MODE): 15 s dão ~2 tentativas
    # inteiras. Com o robô respondendo, sai na 1ª leitura.
    ESPERA_ESTADO_S = 15.0
    INTERVALO_ESTADO_S = 0.5

    def ler_estado(self) -> tuple[object, object]:
        """Lê o FSM até ele estar num estado estável (mole ou 801/0), por até ESPERA_ESTADO_S.

        Uma leitura só falhava às vezes (logo depois de conectar o LocoClient responde 3102 → None,
        ou o MODE ainda está mudando) e a partida pelo controle dizia "não estou em equilíbrio" com
        o robô em pé (2026-11-05). Reler não mexe no robô.
        """
        fim = time.monotonic() + self.ESPERA_ESTADO_S
        while True:
            fsm_id, fsm_mode = self.robot.state("Antes de inicializar")
            if (fsm_id, fsm_mode) == (801, 0) or fsm_id in SEM_TORQUE_OU_DAMP or time.monotonic() >= fim:
                return fsm_id, fsm_mode
            time.sleep(self.INTERVALO_ESTADO_S)

    def initialize(self, so_equilibrio: bool = False) -> bool:
        """F1+UP: damp → em pé (FSM 4) → equilíbrio (FSM 801). Robô no suporte.

        O damp solta todos os motores: só começa por ele se o robô já está mole (FSM 0 ou 1).
        Já em equilíbrio (FSM 801, rodada anterior) aproveita sem passar pelo damp; em pé em
        qualquer outro modo, recusa — o damp derrubaria o robô fora do suporte.
        `so_equilibrio` (partida pelo controle, robô fora do suporte): só aceita FSM 801.
        """
        fsm_id, fsm_mode = self.ler_estado()
        if em_equilibrio(fsm_id, fsm_mode):
            # Em pé: só captura a postura. Sem damp mesmo se a segunda leitura do initialize_to_balance
            # não confirmar 801/0 (antes caía no damp e derrubava o robô).
            return bool(self.robot.initialize_to_balance(permitir_damp=False))
        if so_equilibrio:
            self.robot.log(
                f"ERRO: robô em FSM_ID={fsm_id}, FSM_MODE={fsm_mode} depois de {self.ESPERA_ESTADO_S:.0f} s: "
                "pelo controle só começo em equilíbrio (FSM 801)"
            )
            return False
        elif fsm_id not in SEM_TORQUE_OU_DAMP:
            self.robot.log(
                f"ERRO: robô em FSM_ID={fsm_id}, FSM_MODE={fsm_mode}: não inicializo (o damp o derrubaria). "
                "No suporte, ponha-o em damp (controle ou scripts/robo_emergencia.py) e suba de novo."
            )
            return False
        return bool(self.robot.initialize_to_balance())

    def posture(self, nome: str) -> bool:
        velocidade, funcao = self._posturas[nome]
        if velocidade is None:
            return bool(funcao())
        anterior = self.robot.max_joint_speed
        try:
            self.robot.max_joint_speed = velocidade
            return bool(funcao())
        finally:
            self.robot.max_joint_speed = anterior

    def velocity(self, vx: float, vyaw: float) -> None:
        # Última barreira antes do robô: nunca para trás, nunca acima do teto, nunca NaN/inf (vira parado).
        vx = min(max(0.0, vx), VX_MAX) if math.isfinite(vx) else 0.0
        vyaw = max(-VYAW_MAX, min(VYAW_MAX, vyaw)) if math.isfinite(vyaw) else 0.0
        self.robot.loco.SetVelocity(vx, 0.0, vyaw, 0.5)

    def stop(self) -> None:
        self.robot.loco.StopMove()

    def yaw(self) -> float | None:
        estado = self.robot.low_state
        return None if estado is None else float(estado.imu_state.rpy[2])

    def meia_volta(self, cfg: MeiaVoltaConfig, interromper: threading.Event, log) -> str:
        """Gira 180° à esquerda medindo o yaw da IMU, depois anda `passo_m`. "" = deu certo."""
        dt = 0.02  # 50 Hz
        try:
            girado, anterior, t0, ultimo_log = 0.0, self.yaw(), time.monotonic(), 0.0
            while not interromper.is_set():
                yaw = self.yaw()
                if yaw is not None and math.isfinite(yaw) and anterior is not None:
                    girado = acumular(girado, anterior, yaw)
                    anterior = yaw
                elif yaw is not None and math.isfinite(yaw):
                    anterior = yaw  # 1ª leitura válida
                sem_angulo = yaw is None or not math.isfinite(yaw) or anterior is None
                agora = time.monotonic()
                vyaw, estado = passo_giro(cfg, None if sem_angulo else girado, agora - t0)
                if estado == CHEGOU:
                    break
                if estado != GIRANDO:
                    return estado
                if interromper.is_set():
                    break
                self.velocity(0.0, vyaw)
                if agora - ultimo_log >= 0.5:
                    ultimo_log = agora
                    log(f"meia_volta: girando (girado={math.degrees(girado):+.0f}°)")
                interromper.wait(dt)
            if interromper.is_set():
                return "interrompida"
            self.stop()
            if cfg.vx_passo > 0:  # sem velocidade não há passo (e duracao_passo dividiria por zero)
                fim = time.monotonic() + duracao_passo(cfg)
                while time.monotonic() < fim:
                    if interromper.is_set():
                        return "interrompida"
                    self.velocity(cfg.vx_passo, 0.0)
                    interromper.wait(0.1)
            return ""
        finally:
            self.stop()

    def shutdown(self) -> None:
        """Braços de volta ao equilíbrio e arm_sdk solto; o robô continua em pé (FSM 801)."""
        self.robot.shutdown()


def serve(body: object, inp: IO[str], out: IO[str]) -> None:
    """Atende ordens até `shutdown` ou até a entrada fechar (que também vira shutdown).

    Esta thread lê a entrada e atende `velocidade`/`parar` na hora; as outras ordens vão para
    uma fila, atendidas uma por vez pela thread executora (a única que chama
    initialize/posture/shutdown do corpo).
    """
    escrita = threading.Lock()

    def reply(ordem: dict, ok: bool, erro: str = "") -> None:
        resposta = {"id": ordem["id"]} if "id" in ordem else {}
        resposta["ok"] = ok
        if erro:
            resposta["erro"] = erro
        with escrita:
            out.write(json.dumps(resposta) + "\n")
            out.flush()

    fila: queue.Queue = queue.Queue()
    interromper = threading.Event()  # o `parar` interrompe a meia_volta em andamento

    def executar() -> None:
        while True:
            ordem = fila.get()
            if ordem is None:
                return
            try:
                cmd = ordem["cmd"]
                if cmd == "initialize":
                    reply(ordem, bool(body.initialize(bool(ordem.get("so_equilibrio", False)))))
                elif cmd == "posture":
                    reply(ordem, bool(body.posture(ordem["nome"])))
                elif cmd == "meia_volta" and hasattr(body, "meia_volta"):
                    erro = body.meia_volta(
                        MeiaVoltaConfig(**ordem["cfg"]), interromper, lambda t: print(t, file=sys.stderr)
                    )
                    reply(ordem, not erro, erro)
                else:
                    reply(ordem, False, f"ordem desconhecida {cmd!r}")
            except Exception as exc:  # erro do SDK numa ordem não derruba o processo
                reply(ordem, False, repr(exc))

    executora = threading.Thread(target=executar, daemon=True)
    executora.start()
    final: dict = {}  # entrada fechada sem ordem de shutdown: a resposta final vai sem id
    for line in inp:
        ordem: object = {}
        try:
            ordem = json.loads(line)
            cmd = ordem["cmd"]
            if cmd == "velocidade":
                body.velocity(float(ordem["vx"]), float(ordem["vyaw"]))
            elif cmd == "parar":
                interromper.set()
                body.stop()
            elif cmd == "shutdown":
                final = ordem
                break
            else:
                if cmd == "meia_volta":
                    interromper.clear()  # aqui, não na executora: um `parar` já lido não pode ser apagado
                fila.put(ordem)
        except Exception as exc:
            if isinstance(ordem, dict) and ordem.get("cmd") in ("velocidade", "parar"):
                print(f"body_worker: {ordem['cmd']} falhou: {exc!r}", file=sys.stderr)  # sem resposta
            else:
                reply(ordem if isinstance(ordem, dict) else {}, False, repr(exc))
    interromper.set()  # a meia_volta em andamento não segue sem supervisão
    try:  # entrada fechada ou shutdown: para de andar já, antes de esperar a postura em andamento
        body.stop()
    except Exception as exc:
        print(f"body_worker: parar no encerramento falhou: {exc!r}", file=sys.stderr)
    fila.put(None)
    executora.join()
    try:
        body.shutdown()
    finally:
        reply(final, True)


TRAVA = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "ipe-body_worker.lock")
VX_MAX, VYAW_MAX = 0.5, 0.8  # m/s e rad/s: os mesmos tetos de core.approach.LIMITES_OPERACAO
ESPERA_TRAVA_S = 20.0  # o worker anterior ainda pode estar devolvendo os braços


def travar_corpo(caminho: str = TRAVA, espera_s: float = ESPERA_TRAVA_S) -> IO[str] | None:
    """Um só body_worker comanda o robô por vez (em 2026-11-05 duas subidas sobrepostas
    terminaram com o robô no chão). Espera o anterior soltar a trava; desiste depois de espera_s.
    O sistema solta a trava quando o processo morre, mesmo morto à força."""
    import fcntl

    arquivo = open(caminho, "w")
    fim = time.monotonic() + espera_s
    while True:
        try:
            fcntl.flock(arquivo, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return arquivo
        except BlockingIOError:
            if time.monotonic() >= fim:
                arquivo.close()
                return None
            time.sleep(0.5)


def main() -> int:
    poses_dir, network_interface = sys.argv[1], sys.argv[2]
    rest_forward_pulse = len(sys.argv) < 4 or sys.argv[3] != "sem_passo"
    # O Ctrl+C do terminal chega a todo o grupo de processos; quem decide o encerramento é o
    # body_node (ele manda `shutdown` na hora certa).
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    # O G1ArmController escreve o log com print(): o stdout real fica só para o protocolo e o
    # resto vai para o stderr (que aparece no log do launch).
    protocolo = os.fdopen(os.dup(sys.stdout.fileno()), "w")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    # Linha a linha: antes o log do controlador (FSM lido etc.) só aparecia quando o worker saía, e a
    # recusa "não está em equilíbrio" ficava sem o motivo no log da rotina.
    sys.stdout.reconfigure(line_buffering=True)
    trava = travar_corpo()  # guardada até o processo sair
    if trava is None:
        protocolo.write(json.dumps({"ok": False, "erro": "outro body_worker já comanda o robô"}) + "\n")
        protocolo.flush()
        return 1
    try:
        body = G1Body(poses_dir, network_interface, rest_forward_pulse)
    except Exception as exc:
        protocolo.write(json.dumps({"ok": False, "erro": repr(exc)}) + "\n")
        protocolo.flush()
        return 1
    protocolo.write(json.dumps({"ok": True}) + "\n")
    protocolo.flush()
    serve(body, sys.stdin, protocolo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
