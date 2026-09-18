from vision_msgs.msg import Detection2D, ObjectHypothesisWithPose


def build_detection(
    bbox: tuple[int, int, int, int], name: str | None, score: float
) -> Detection2D:
    x1, y1, x2, y2 = bbox

    detection = Detection2D()
    detection.bbox.center.position.x = float((x1 + x2) / 2)
    detection.bbox.center.position.y = float((y1 + y2) / 2)
    detection.bbox.size_x = float(x2 - x1)
    detection.bbox.size_y = float(y2 - y1)

    hypothesis = ObjectHypothesisWithPose()
    hypothesis.hypothesis.class_id = name if name else "desconhecido"
    hypothesis.hypothesis.score = float(score)
    detection.results.append(hypothesis)

    return detection
