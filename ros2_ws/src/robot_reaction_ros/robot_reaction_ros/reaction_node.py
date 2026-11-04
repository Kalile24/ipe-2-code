from __future__ import annotations

import json
import os
import time

import rclpy
import yaml
from ament_index_python.packages import get_package_share_directory
from rcl_interfaces.msg import SetParametersResult
from rclpy.node import Node
from rclpy.qos import QoSProfile
from std_msgs.msg import String
from vision_msgs.msg import Detection2DArray

from core.reaction_policy import ReactionPolicy, load_reactions


TODOS = "todos"


class ReactionNode(Node):
    """Escuta as detecções e publica a reação de quem a merece.

    - `gesto` → /reaction/gesture (nome do gesto; gesture_node).
    - `passos` → /reaction/rotina (JSON {"pessoa", "passos"}; body_node).
    Comando manual de teste: `ros2 param set /reaction_node liberar <nome|todos>`
    (scripts/robo_liberar_cumprimento.sh).
    """

    def __init__(self) -> None:
        super().__init__("reaction_node")
        self.declare_parameter("reactions_file", "")
        self.declare_parameter("detections_topic", "/face_recognition/detections")
        self.declare_parameter("confirm_frames", 5)
        self.declare_parameter("person_cooldown_s", 300.0)
        self.declare_parameter("global_cooldown_s", 10.0)
        self.declare_parameter("absence_s", 5.0)
        self.declare_parameter("liberar", "")

        path = self.get_parameter("reactions_file").value or os.path.join(
            get_package_share_directory("robot_reaction_ros"), "config", "reactions.yaml"
        )
        with open(path) as f:  # arquivo ausente ou mapa inválido derrubam o nó na partida
            reactions = load_reactions(yaml.safe_load(f))
        # float()/int(): `-p x:=60` chega como int e `-p x:=5.0` como float
        self._policy = ReactionPolicy(
            reactions,
            confirm_frames=int(self.get_parameter("confirm_frames").value),
            person_cooldown_s=float(self.get_parameter("person_cooldown_s").value),
            global_cooldown_s=float(self.get_parameter("global_cooldown_s").value),
            absence_s=float(self.get_parameter("absence_s").value),
        )

        detections_topic = self.get_parameter("detections_topic").value
        self._publisher = self.create_publisher(String, "/reaction/gesture", 10)
        self._routine_publisher = self.create_publisher(String, "/reaction/rotina", 10)
        self._subscription = self.create_subscription(
            Detection2DArray, detections_topic, self._on_detections, QoSProfile(depth=1)
        )
        self.add_on_set_parameters_callback(self._on_set_parameters)
        self.get_logger().info(f"mapa {path}: {reactions}; assinando {detections_topic}")

    def _on_set_parameters(self, params: list) -> SetParametersResult:
        for p in params:
            if p.name != "liberar":
                continue
            nome = str(p.value).strip()
            try:
                self._policy.release(None if nome in ("", TODOS) else nome)
            except KeyError as exc:
                return SetParametersResult(successful=False, reason=str(exc))
            self.get_logger().info(f"liberado: {nome or TODOS} pode ser cumprimentado de novo")
        return SetParametersResult(successful=True)

    def _on_detections(self, msg: Detection2DArray) -> None:
        seen = [(d.results[0].id, d.results[0].score) for d in msg.detections if d.results]
        hit = self._policy.update(seen, time.monotonic())
        if hit is None:
            return
        nome, reacao = hit
        self.get_logger().info(f"reagindo a {nome}: {reacao}")
        if isinstance(reacao, str):
            self._publisher.publish(String(data=reacao))
        else:
            payload = json.dumps({"pessoa": nome, "passos": reacao}, ensure_ascii=False)
            self._routine_publisher.publish(String(data=payload))


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = ReactionNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():  # o Ctrl+C já pode ter desligado o contexto
            rclpy.shutdown()


if __name__ == "__main__":
    main()
