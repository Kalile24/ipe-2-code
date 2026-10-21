from __future__ import annotations

import threading
import time
from typing import Callable

import rclpy
from rcl_interfaces.msg import SetParametersResult
from rclpy.node import Node
from std_msgs.msg import String
from std_srvs.srv import SetBool

from core.reaction_policy import GESTOS, RELEASE_ARM


def _sdk_client(network_interface: str, rpc_timeout_s: float) -> object:
    # Import tardio: desarmado, o nó roda sem o SDK da Unitree (notebook, Docker).
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    from unitree_sdk2py.g1.arm.g1_arm_action_client import G1ArmActionClient

    ChannelFactoryInitialize(0, network_interface)
    client = G1ArmActionClient()
    client.SetTimeout(rpc_timeout_s)
    client.Init()
    return client


class GestureNode(Node):
    """Único nó que fala com o firmware: executa gestos prontos (G1ArmActionClient).

    Nasce desarmado (dry-run). Nunca troca o modo do robô nem usa controle de baixo nível: o
    operador põe o robô em pé pelo controle. Spec: 2026-10-21-robot-reaction-design.md.
    """

    def __init__(self, client_factory: Callable[[str, float], object] = _sdk_client) -> None:
        super().__init__("gesture_node")
        self.declare_parameter("armed", False)
        self.declare_parameter("network_interface", "eth0")
        self.declare_parameter("hold_s", 2.0)
        self.declare_parameter("rpc_timeout_s", 10.0)
        self._network_interface = self.get_parameter("network_interface").value
        self._hold_s = float(self.get_parameter("hold_s").value)
        self._rpc_timeout_s = float(self.get_parameter("rpc_timeout_s").value)

        self._client_factory = client_factory
        self._client = None
        self._armed = False
        self._busy = threading.Lock()
        self._worker: threading.Thread | None = None

        self._status_pub = self.create_publisher(String, "/reaction/gesture_status", 10)
        self._subscription = self.create_subscription(String, "/reaction/gesture", self._on_gesture, 10)
        self._service = self.create_service(SetBool, "~/set_armed", self._on_set_armed)

        # `is True`: um "true"/"false" que chegasse como string seria verdadeiro e armaria o braço.
        if self.get_parameter("armed").value is True:
            self._set_armed(True)
        # `armed` só vale na partida; depois, só pelo serviço. Sem isto, `ros2 param set armed false`
        # responderia sucesso e o braço continuaria armado.
        self.add_on_set_parameters_callback(self._on_set_parameters)

    def _publish(self, text: str) -> None:
        self.get_logger().info(text)
        self._status_pub.publish(String(data=text))

    def _set_armed(self, armed: bool) -> tuple[bool, str]:
        if armed and self._client is None:
            try:
                self._client = self._client_factory(self._network_interface, self._rpc_timeout_s)
            except Exception as exc:  # sem SDK ou sem DDS: continua desarmado
                self._publish(f"failed init {exc!r}")
                return False, repr(exc)
        self._armed = armed
        self._publish("armed" if armed else "disarmed")
        return True, "armed" if armed else "disarmed"

    def _on_set_parameters(self, params: list) -> SetParametersResult:
        if any(p.name == "armed" for p in params):
            return SetParametersResult(successful=False, reason="use o serviço ~/set_armed")
        return SetParametersResult(successful=True)

    def _on_set_armed(self, request: SetBool.Request, response: SetBool.Response) -> SetBool.Response:
        response.success, response.message = self._set_armed(request.data)
        return response

    def _on_gesture(self, msg: String) -> None:
        gesto = msg.data
        if gesto not in GESTOS:
            self._publish(f"rejected unknown {gesto!r}")
            return
        if not self._armed:
            self._publish(f"dry_run {gesto}")
            return
        if not self._busy.acquire(blocking=False):
            self._publish("rejected busy")
            return
        # ExecuteAction bloqueia até o timeout: fora do callback, para não travar o executor do ROS.
        self._worker = threading.Thread(target=self._run, args=(gesto,), daemon=True)
        self._worker.start()

    def _run(self, gesto: str) -> None:
        try:
            self._publish(f"started {gesto}")
            ok = self._execute(gesto)
            if ok:
                time.sleep(self._hold_s)
            released = self._execute(RELEASE_ARM)  # mesmo se o gesto falhou
            if ok and released:
                self._publish(f"done {gesto}")
        finally:
            self._busy.release()

    def _execute(self, gesto: str) -> bool:
        try:
            code = self._client.ExecuteAction(GESTOS[gesto])
        except Exception as exc:  # um erro do SDK não pode deixar o nó preso em "ocupado"
            self._publish(f"failed {gesto} {exc!r}")
            return False
        if code != 0:
            self._publish(f"failed {gesto} code={code}")
            return False
        return True

    def release_if_busy(self) -> None:
        """Ctrl+C no meio de um gesto: tenta soltar o braço antes de sair."""
        if self._client is not None and self._busy.locked():
            self._execute(RELEASE_ARM)


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = GestureNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        if node is not None:
            node.release_if_busy()
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():  # o Ctrl+C já pode ter desligado o contexto
            rclpy.shutdown()


if __name__ == "__main__":
    main()
