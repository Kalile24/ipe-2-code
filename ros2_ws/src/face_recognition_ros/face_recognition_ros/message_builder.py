from __future__ import annotations

from std_msgs.msg import Header
from vision_msgs.msg import Detection2D, ObjectHypothesisWithPose


def clip_bbox(bbox: tuple[int, int, int, int], image_shape: tuple[int, int] | None) -> tuple[int, int, int, int]:
    """Ordena os cantos e recorta a caixa aos limites (altura, largura) da imagem. O SCRFD pode
    devolver coordenadas negativas ou além da borda em rostos cortados pelo enquadramento.
    Uma caixa totalmente fora vira área zero — o chamador deve descartá-la (`bbox_area == 0`)."""
    x1, y1, x2, y2 = bbox
    x1, x2 = min(x1, x2), max(x1, x2)
    y1, y2 = min(y1, y2), max(y1, y2)
    if image_shape is None:
        return x1, y1, x2, y2
    h, w = image_shape[0], image_shape[1]
    x1, x2 = max(0, min(x1, w)), max(0, min(x2, w))
    y1, y2 = max(0, min(y1, h)), max(0, min(y2, h))
    return x1, y1, x2, y2


def bbox_area(bbox: tuple[int, int, int, int]) -> int:
    x1, y1, x2, y2 = bbox
    return max(0, x2 - x1) * max(0, y2 - y1)


def build_detection(
    bbox: tuple[int, int, int, int],
    name: str | None,
    score: float,
    header: Header | None = None,
    image_shape: tuple[int, int] | None = None,
) -> Detection2D:
    x1, y1, x2, y2 = clip_bbox(bbox, image_shape)

    detection = Detection2D()
    if header is not None:
        detection.header = header  # carimbo do frame em que a caixa foi medida
    # `Detection2D.id` é reservado a rastreio ("same object across messages"); fica vazio.
    # O nome vai só em `results[0].hypothesis.class_id`.
    detection.bbox.center.position.x = float((x1 + x2) / 2)
    detection.bbox.center.position.y = float((y1 + y2) / 2)
    detection.bbox.size_x = float(x2 - x1)
    detection.bbox.size_y = float(y2 - y1)

    hypothesis = ObjectHypothesisWithPose()
    hypothesis.hypothesis.class_id = name if name else "desconhecido"
    hypothesis.hypothesis.score = float(score)
    detection.results.append(hypothesis)

    return detection
