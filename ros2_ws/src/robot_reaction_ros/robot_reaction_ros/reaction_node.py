from __future__ import annotations

import json
import os
import time

import rclpy
import yaml
from ament_index_python.packages import get_package_share_directory
from rcl_interfaces.msg import SetParametersResult
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import QoSProfile
from std_msgs.msg import String
from vision_msgs.msg import Detection2DArray

from core.reaction_policy import ReactionPolicy, load_reactions
from robot_reaction_interfaces.action import Rotina


TODOS = "todos"


class ReactionNode(Node):
    """Escuta as detecções e publica a reação de quem a merece.

    - `gesto` → /reaction/gesture (nome do gesto; gesture_node, no robo.launch.py).
    - `passos` → ação /reaction/rotina (body_node, no rotina.launch.py). Uma rotina por vez:
      enquanto ela roda, ninguém mais é cumprimentado.
    Se ninguém executa a reação (nó do outro launch) ou o body_node recusa a rotina, a pessoa
    não conta como cumprimentada (ReactionPolicy.forget).
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
        self._rotina = ActionClient(self, Rotina, "/reaction/rotina")
        self._em_andamento: str | None = None  # pessoa cuja rotina o body_node está executando
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
        if self._em_andamento is not None and not self._rotina.server_is_ready():
            # body_node morreu no meio: o resultado nunca vai chegar
            self.get_logger().warn(f"rotina de {self._em_andamento}: o body_node sumiu")
            self._em_andamento = None
        hit = self._policy.update(seen, time.monotonic(), allow_fire=self._em_andamento is None)
        if hit is None:
            return
        nome, reacao = hit
        log = self.get_logger()
        if isinstance(reacao, str):
            if self._publisher.get_subscription_count() == 0:
                log.warn(f"{nome}: ninguém executa gestos (gesture_node, robo.launch.py); não cumprimentado")
                self._policy.forget(nome)
                return
            log.info(f"reagindo a {nome}: {reacao}")
            self._publisher.publish(String(data=reacao))
            return
        if not self._rotina.server_is_ready():
            log.warn(f"{nome}: ninguém executa rotinas (body_node, rotina.launch.py); não cumprimentado")
            self._policy.forget(nome)
            return
        log.info(f"reagindo a {nome}: rotina de {len(reacao)} passos")
        self._em_andamento = nome
        goal = Rotina.Goal(pessoa=nome, passos_json=json.dumps(reacao, ensure_ascii=False))
        self._rotina.send_goal_async(goal).add_done_callback(lambda future: self._on_goal_response(nome, future))

    def destroy_node(self) -> None:
        self._rotina.destroy()  # antes do nó: no Foxy, o __del__ dele depois reclama do nó destruído
        super().destroy_node()

    def _on_goal_response(self, nome: str, future: object) -> None:
        handle = future.result()
        if self._em_andamento != nome:  # já dado como perdido (body_node sumiu)
            return
        if not handle.accepted:  # inicializando, ocupado ou encerrando: o motivo está no rotina_status
            self.get_logger().warn(f"{nome}: o body_node recusou a rotina; não cumprimentado")
            self._policy.forget(nome)
            self._em_andamento = None
            return
        handle.get_result_async().add_done_callback(lambda future: self._on_result(nome, future))

    def _on_result(self, nome: str, future: object) -> None:
        # Rotina que falhou no meio também conta como cumprimento: repetir não consertaria o braço.
        resultado = future.result().result
        self.get_logger().info(f"rotina de {nome}: {'fim' if resultado.sucesso else resultado.mensagem}")
        self._em_andamento = None


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
