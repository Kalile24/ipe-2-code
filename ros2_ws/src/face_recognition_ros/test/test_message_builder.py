from face_recognition_ros.message_builder import build_detection


def test_build_detection_known_person_sets_class_id_and_score():
    detection = build_detection(bbox=(10, 20, 110, 220), name="alice", score=0.87)

    assert detection.results[0].hypothesis.class_id == "alice"
    assert detection.results[0].hypothesis.score == 0.87


def test_build_detection_unknown_person_uses_desconhecido_label():
    detection = build_detection(bbox=(0, 0, 50, 50), name=None, score=0.2)

    assert detection.results[0].hypothesis.class_id == "desconhecido"


def test_build_detection_bbox_center_and_size():
    detection = build_detection(bbox=(10, 20, 110, 220), name="alice", score=0.87)

    assert detection.bbox.center.position.x == 60.0
    assert detection.bbox.center.position.y == 120.0
    assert detection.bbox.size_x == 100.0
    assert detection.bbox.size_y == 200.0
