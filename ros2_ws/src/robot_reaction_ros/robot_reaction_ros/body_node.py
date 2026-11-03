from __future__ import annotations

import functools
import json
import os
import select
import signal
import subprocess
import sys
import threading
from typing import Callable

import rclpy
from ament_index_python.packages import get_package_share_directory
from rcl_interfaces.msg import SetParametersResult
from rclpy.node import Node
from std_msgs.msg import String

from core.piper_voice import DEFAULT_URL, say
from core.reaction_policy import ReactionConfigError, validate_steps
from core.routine import run_routine


class SubprocessBody:
    """O corpo num processo sem ROS (body_worker): rclpy e SDK da Unitree não convivem.

    Mesma interface que o body_node espera (initialize/posture/shutdown); cada chamada é uma
    linha JSON para o body_worker e espera a resposta dele.
    """

    def __init__(self, poses_dir: str, network_interface: str, command: list[str] | None = None) -> None:
        command = command or [sys.executable, "-m", "robot_reaction_ros.body_worker", poses_dir, network_interface]
        # stderr herdado: o log do G1ArmController aparece junto com o do launch.
        self._proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        hello = self._read(timeout_s=60.0)
        if not hello.get("ok"):
            self._proc.kill()
            raise RuntimeError(f"body_worker não subiu: {hello.get('erro', hello)}")

    def _read(self, timeout_s: float) -> dict:
        prontos, _, _ = select.select([self._proc.stdout], [], [], timeout_s)
        line = self._proc.stdout.readline() if prontos else ""
        if not line:
            return {"ok": False, "erro": f"sem resposta do body_worker em {timeout_s:.0f} s"}
        return json.loads(line)

    def _call(self, ordem: dict, timeout_s: float) -> bool:
        if self._proc.poll() is not None:
            return False
        self._proc.stdin.write(json.dumps(ordem) + "\n")
        self._proc.stdin.flush()
        return bool(self._read(timeout_s).get("ok"))

    def initialize(self) -> bool:
        return self._call({"cmd": "initialize"}, timeout_s=120.0)

    def posture(self, nome: str) -> bool:
        return self._call({"cmd": "posture", "nome": nome}, timeout_s=120.0)

    def shutdown(self) -> None:
        try:
            self._call({"cmd": "shutdown"}, timeout_s=60.0)
        finally:
            if self._proc.poll() is None:
                try:
                    self._proc.wait(10.0)
                except subprocess.TimeoutExpired:
                    self._proc.kill()


class BodyNode(Node):
    """Único dono dos braços e da voz: executa as rotinas que chegam em /reaction/rotina.

    Os braços são comandados pelo body_worker (processo sem ROS, ver body_worker.py).

    Desarmado (padrão): fala de verdade, mas as posturas só aparecem no log (dry-run).
    Armado (`armed:=true`, só na partida): ao subir faz a inicialização do F1+UP e depois executa
    as posturas. Status em /reaction/rotina_status. Ctrl+C: espera o passo atual, devolve os braços
    ao equilíbrio e solta o arm_sdk.
    """

    def __init__(
        self,
        body_factory: Callable[[str, str], object] = SubprocessBody,
        speak: Callable[..., None] = say,
    ) -> None:
        super().__init__("body_node")
        self.declare_parameter("armed", False)
        # "" = as poses instaladas com o pacote (share/robot_reaction_ros/poses)
        self.declare_parameter("poses_dir", "")
        self.declare_parameter("network_interface", "eth0")
        self.declare_parameter("pausa_s", 0.5)
        self.declare_parameter("tts_url", DEFAULT_URL)
        self.declare_parameter("tts_timeout_s", 60.0)
        self._pausa_s = float(self.get_parameter("pausa_s").value)
        self._speak = functools.partial(
            speak,
            url=self.get_parameter("tts_url").value,
            timeout_s=float(self.get_parameter("tts_timeout_s").value),
        )

        self._body = None
        self._ready = False  # inicializado (FSM 801): só então as posturas mexem o braço
        self._stop = threading.Event()
        self._busy = threading.Lock()
        self._worker: threading.Thread | None = None

        self._status_pub = self.create_publisher(String, "/reaction/rotina_status", 10)
        self._subscription = self.create_subscription(String, "/reaction/rotina", self._on_routine, 10)
        # `armed` só vale na partida: armar no meio faria o robô cair em damp sem aviso.
        self.add_on_set_parameters_callback(self._on_set_parameters)

        # `is True`: um "true" que chegasse como string seria verdadeiro e armaria o braço.
        if self.get_parameter("armed").value is True:
            poses_dir = self.get_parameter("poses_dir").value or os.path.join(
                get_package_share_directory("robot_reaction_ros"), "poses"
            )
            network_interface = self.get_parameter("network_interface").value
            self._busy.acquire()  # nenhuma rotina enquanto inicializa
            self._worker = threading.Thread(
                target=self._initialize, args=(body_factory, poses_dir, network_interface), daemon=True
            )
            self._worker.start()
        else:
            self._publish("desarmado: posturas só no log, fala de verdade")

    def _publish(self, text: str) -> None:
        self.get_logger().info(text)
        try:
            self._status_pub.publish(String(data=text))
        except Exception:  # depois do Ctrl+C o contexto ROS já fechou; o log basta
            pass

    def _on_set_parameters(self, params: list) -> SetParametersResult:
        if any(p.name == "armed" for p in params):
            return SetParametersResult(successful=False, reason="armed só vale na partida (reinicie o nó)")
        return SetParametersResult(successful=True)

    def _initialize(self, body_factory: Callable[[str, str], object], poses_dir: str, network_interface: str) -> None:
        try:
            self._publish("inicializando: damp → em pé → equilíbrio (robô no suporte)")
            try:
                self._body = body_factory(poses_dir, network_interface)
                self._ready = self._body.initialize()
            except Exception as exc:  # sem SDK, sem poses ou sem DDS
                self._publish(f"falha na inicialização: {exc!r}")
                return
            if self._ready:
                self._publish("pronto: em equilíbrio, esperando reconhecimento")
            else:
                self._publish("falha na inicialização (veja o log do G1ArmController); posturas só no log")
        finally:
            self._busy.release()

    def _on_routine(self, msg: String) -> None:
        try:
            dados = json.loads(msg.data)
            pessoa = str(dados["pessoa"])
            passos = validate_steps(pessoa, dados["passos"])
        except (ValueError, KeyError, TypeError, ReactionConfigError) as exc:
            self._publish(f"rotina rejeitada (mensagem inválida): {exc}")
            return
        if self._stop.is_set():
            return
        if not self._busy.acquire(blocking=False):
            self._publish(f"rotina de {pessoa} rejeitada: ocupado")
            return
        self._worker = threading.Thread(target=self._run, args=(pessoa, passos), daemon=True)
        self._worker.start()

    def _run(self, pessoa: str, passos: list[dict[str, str]]) -> None:
        try:
            self._publish(f"rotina de {pessoa}: início")
            ok = run_routine(
                passos,
                postura=self._posture,
                falar=self._speak,
                pausa_s=self._pausa_s,
                log=self._publish,
                deve_parar=self._stop.is_set,
            )
            self._publish(f"rotina de {pessoa}: {'fim' if ok else 'falhou'}")
        finally:
            self._busy.release()

    def _posture(self, nome: str) -> bool:
        if not self._ready:
            self._publish(f"dry_run postura {nome}")
            return True
        return self._body.posture(nome)

    def shutdown(self, timeout_s: float = 90.0) -> None:
        """Ctrl+C: espera o passo em andamento terminar e solta os braços."""
        self._stop.set()
        log = self.get_logger()
        if self._worker is not None and self._worker.is_alive():
            log.info("esperando o passo atual terminar antes de soltar os braços...")
            self._worker.join(timeout_s)
        if self._body is not None:
            log.info("devolvendo os braços ao equilíbrio e soltando o arm_sdk...")
            try:
                self._body.shutdown()
            except Exception as exc:
                log.error(f"falha ao soltar os braços: {exc!r}; use F1+RIGHT no controle")


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = BodyNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # O `ros2 launch` repassa o Ctrl+C como um segundo SIGINT: sem isto ele interromperia a
        # devolução dos braços no meio.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if node is not None:
            node.shutdown()
            node.destroy_node()
        if rclpy.ok():  # o Ctrl+C já pode ter desligado o contexto
            rclpy.shutdown()


if __name__ == "__main__":
    main()
