from __future__ import annotations

import rclpy
from cv_bridge import CvBridge, CvBridgeError
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image
from vision_msgs.msg import Detection2DArray

from core.config import DB_PATH, DET_SIZE, MODEL_NAME, MODEL_ROOT, SIMILARITY_THRESHOLD
from core.face_engine import FaceEngine
from core.identity_store import IdentityStore

from face_recognition_ros.message_builder import bbox_area, build_detection, clip_bbox

# Perfis aceitos no parâmetro `image_qos`. `sensor_data` (BEST_EFFORT) é o padrão porque
# uma assinatura best-effort recebe de publishers RELIABLE *e* BEST_EFFORT (tabela de
# compatibilidade do ROS2); uma assinatura RELIABLE fica muda, sem erro, diante de uma
# câmera publicando com `color_qos:=SENSOR_DATA`. Profundidade 1 nos dois perfis: com o
# reconhecimento mais lento que a câmera, a fila guarda só o frame mais NOVO — por isso o
# nó não precisa pular frames por conta própria (o `qos_profile_sensor_data` pronto do
# rclpy tem depth 5 e faria o nó processar o frame mais velho).
_IMAGE_QOS = {
    "sensor_data": QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST, depth=1),
    "default": QoSProfile(reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST, depth=1),
}


class FaceRecognitionNode(Node):
    def __init__(self) -> None:
        super().__init__("face_recognition_node")

        self.declare_parameter("image_topic", "/camera/color/image_raw")
        self.declare_parameter("detections_topic", "/face_recognition/detections")
        self.declare_parameter("image_qos", "sensor_data")
        # No Foxy os parâmetros não têm tipo fixo: `similarity_threshold:=1` chega como int e o
        # float() abaixo resolve.
        self.declare_parameter("similarity_threshold", SIMILARITY_THRESHOLD)
        self.declare_parameter("db_path", DB_PATH)
        self.declare_parameter("model_name", MODEL_NAME)
        self.declare_parameter("model_root", MODEL_ROOT or "")
        # Execution providers do ONNX Runtime em ordem de preferência, separados por vírgula
        # (argumento de launch é sempre texto). Vazio = default do InsightFace. No robô:
        # "TensorrtExecutionProvider,CUDAExecutionProvider,CPUExecutionProvider".
        self.declare_parameter("onnx_providers", "")

        image_topic = self.get_parameter("image_topic").value
        detections_topic = self.get_parameter("detections_topic").value
        image_qos_name = self.get_parameter("image_qos").value
        self._threshold = float(self.get_parameter("similarity_threshold").value)
        db_path = self.get_parameter("db_path").value
        model_name = self.get_parameter("model_name").value
        model_root = self.get_parameter("model_root").value or None
        providers = [p.strip() for p in self.get_parameter("onnx_providers").value.split(",") if p.strip()] or None

        if image_qos_name not in _IMAGE_QOS:
            raise ValueError(f"image_qos deve ser um de {sorted(_IMAGE_QOS)}, não {image_qos_name!r}")

        self._bridge = CvBridge()
        self._engine = FaceEngine(
            det_size=DET_SIZE, model_name=model_name, model_root=model_root, providers=providers
        )
        # O ORT não lança quando um provider pedido não existe — só avisa e cai pro próximo.
        # Logar o que ficou ativo é o jeito de saber se a GPU está mesmo em uso.
        active = self._engine.active_providers()
        self.get_logger().info(f"providers ativos: {active}")
        missing = {p for p in providers or [] if p != "CPUExecutionProvider"} - {
            p for task_providers in active.values() for p in task_providers
        }
        if missing:
            self.get_logger().warn(f"providers pedidos mas NÃO ativos (rodando sem eles): {sorted(missing)}")
        self._store = IdentityStore(db_path, model_name=model_name)
        self._store.load()
        if not self._store.embeddings:
            self.get_logger().warn(
                f"Nenhuma identidade cadastrada em {db_path}; "
                "todos os rostos serão marcados como desconhecido."
            )

        self._subscription = self.create_subscription(
            Image, image_topic, self._on_image, _IMAGE_QOS[image_qos_name]
        )
        self._publisher = self.create_publisher(Detection2DArray, detections_topic, QoSProfile(depth=1))
        self.get_logger().info(
            f"assinando {image_topic} (qos={image_qos_name}), publicando em {detections_topic}, "
            f"limiar={self._threshold}, modelo={model_name}"
        )

    def _on_image(self, msg: Image) -> None:
        try:
            frame = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except CvBridgeError as exc:
            self.get_logger().warn(f"Falha ao converter frame: {exc}")
            return

        shape = (frame.shape[0], frame.shape[1])
        detections = []
        try:
            for face in self._engine.extract_faces(frame):
                bbox = clip_bbox(face.bbox, shape)
                if bbox_area(bbox) == 0:
                    continue  # caixa totalmente fora do enquadramento
                name, score = self._store.match(face.embedding, self._threshold)
                detections.append((bbox, name, score))
        except Exception as exc:  # um frame ruim não pode derrubar o nó
            self.get_logger().error(f"Falha no reconhecimento deste frame: {exc!r}")
            return

        detections_msg = Detection2DArray()
        detections_msg.header = msg.header
        detections_msg.detections = [
            build_detection(bbox, name, score, header=msg.header, image_shape=shape)
            for bbox, name, score in detections
        ]
        self._publisher.publish(detections_msg)


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = FaceRecognitionNode()
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
