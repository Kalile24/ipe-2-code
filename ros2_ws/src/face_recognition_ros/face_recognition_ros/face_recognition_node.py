import rclpy
from cv_bridge import CvBridge, CvBridgeError
from rclpy.node import Node
from rclpy.qos import QoSProfile
from sensor_msgs.msg import Image
from vision_msgs.msg import Detection2DArray

from core.config import DB_PATH, DET_SIZE, RECOGNITION_INTERVAL_FRAMES, SIMILARITY_THRESHOLD
from core.face_engine import FaceEngine
from core.identity_store import IdentityStore

from face_recognition_ros.message_builder import build_detection


class FaceRecognitionNode(Node):
    def __init__(self) -> None:
        super().__init__("face_recognition_node")

        self.declare_parameter("image_topic", "/camera/color/image_raw")
        self.declare_parameter("detections_topic", "/face_recognition/detections")
        self.declare_parameter("similarity_threshold", SIMILARITY_THRESHOLD)
        self.declare_parameter("db_path", DB_PATH)

        image_topic = self.get_parameter("image_topic").value
        detections_topic = self.get_parameter("detections_topic").value
        self._threshold = self.get_parameter("similarity_threshold").value
        db_path = self.get_parameter("db_path").value

        self._bridge = CvBridge()
        self._engine = FaceEngine(det_size=DET_SIZE)
        self._store = IdentityStore(db_path)
        self._store.load()
        if not self._store.embeddings:
            self.get_logger().warn(
                f"Nenhuma identidade cadastrada em {db_path}; "
                "todos os rostos serão marcados como desconhecido."
            )

        self._frame_count = 0
        self._last_detections: list[tuple[tuple[int, int, int, int], str | None, float]] = []

        qos = QoSProfile(depth=1)
        self._subscription = self.create_subscription(Image, image_topic, self._on_image, qos)
        self._publisher = self.create_publisher(Detection2DArray, detections_topic, qos)

    def _on_image(self, msg: Image) -> None:
        try:
            frame = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except CvBridgeError as exc:
            self.get_logger().warn(f"Falha ao converter frame: {exc}")
            return

        if self._frame_count % RECOGNITION_INTERVAL_FRAMES == 0:
            self._last_detections = []
            for face in self._engine.extract_faces(frame):
                name, score = self._store.match(face.embedding, self._threshold)
                self._last_detections.append((face.bbox, name, score))
        self._frame_count += 1

        detections_msg = Detection2DArray()
        detections_msg.header = msg.header
        detections_msg.detections = [
            build_detection(bbox, name, score) for bbox, name, score in self._last_detections
        ]
        self._publisher.publish(detections_msg)


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = FaceRecognitionNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
