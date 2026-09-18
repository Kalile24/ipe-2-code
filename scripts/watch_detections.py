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
            h = d.results[0].hypothesis
            print(f"{h.class_id}: {h.score:.2f}", flush=True)


def main():
    rclpy.init()
    rclpy.spin(Watcher())


if __name__ == "__main__":
    main()
