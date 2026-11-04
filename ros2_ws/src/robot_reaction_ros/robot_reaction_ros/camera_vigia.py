"""Vigia da câmera: reinicia o v4l2_camera_node quando a webcam reconecta ou para de mandar quadros.

No robô a webcam USB cai e volta (troca o /dev/videoN) ou trava sem cair, e o v4l2_camera_node
fica parado nela. O face_recognition_node publica uma Detection2DArray por quadro (mesmo sem
rosto): ficar sem detecções = ficar sem quadros. A decisão (tempos) está em core/vigia.py.
O nó da câmera é morto com SIGKILL (travado, ele não atende SIGINT) e o launch sobe outro
(respawn no face_recognition.launch.py).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import rclpy
from rclpy.node import Node
from vision_msgs.msg import Detection2DArray

REPO = os.path.expanduser(os.environ.get("IPE_REPO", "~/ipe-2-code"))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
from core.vigia import decidir, webcam_conectada_em  # noqa: E402

INTERVALO_S = 0.25


class CameraVigia(Node):
    def __init__(self) -> None:
        super().__init__("camera_vigia")
        self.declare_parameter("detections_topic", "/face_recognition/detections")
        self.declare_parameter("processo", "v4l2_camera_node")
        self._processo = self.get_parameter("processo").value
        self._inicio = time.monotonic()
        self._ultimo: float | None = None  # monotonic do último quadro
        self._reiniciou_em: float | None = None
        self._webcam = webcam_conectada_em()  # hora da conexão que o nó da câmera abriu
        self.create_subscription(Detection2DArray, self.get_parameter("detections_topic").value, self._quadro, 1)
        self.create_timer(INTERVALO_S, self._vigiar)

    def _quadro(self, _msg: Detection2DArray) -> None:
        self._ultimo = time.monotonic()

    def _vigiar(self) -> None:
        agora = time.monotonic()
        webcam = webcam_conectada_em()
        # Caiu e voltou (link recriado): o nó antigo está preso no dispositivo velho.
        reconectou = webcam is not None and webcam != self._webcam
        motivo = decidir(agora, self._inicio, self._ultimo, self._reiniciou_em, reconectou)
        if motivo is None:
            return
        self.get_logger().warn(f"{motivo}: reiniciando o {self._processo}")
        subprocess.run(["pkill", "-9", "-f", f"lib/v4l2_camera/{self._processo}"], check=False)
        self._reiniciou_em = agora
        self._webcam = webcam


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = CameraVigia()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
