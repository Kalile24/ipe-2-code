from __future__ import annotations

import rclpy
from rclpy.node import Node
from vision_msgs.msg import Detection2DArray


class Watcher(Node):
    def __init__(self):
        super().__init__("watch_detections")
        self.create_subscription(Detection2DArray, "/face_recognition/detections", self.cb, 10)

    def cb(self, msg):
        if not msg.detections:
            print("(nenhum rosto)", flush=True)
            return
        for d in msg.detections:
            r = d.results[0]  # vision_msgs do Foxy: id/score direto na hipótese
            print(f"{r.id}: {r.score:.2f}", flush=True)


def main():
    rclpy.init()
    rclpy.spin(Watcher())


if __name__ == "__main__":
    main()
