from face_recognition_ros.message_builder import build_detection


def test_build_detection_known_person_sets_id_and_score():
    detection = build_detection(bbox=(10, 20, 110, 220), name="alice", score=0.87)

    assert detection.results[0].id == "alice"
    assert detection.results[0].score == 0.87


def test_build_detection_unknown_person_uses_desconhecido_label():
    detection = build_detection(bbox=(0, 0, 50, 50), name=None, score=0.2)

    assert detection.results[0].id == "desconhecido"


def test_build_detection_bbox_center_and_size():
    detection = build_detection(bbox=(10, 20, 110, 220), name="alice", score=0.87)

    assert detection.bbox.center.x == 60.0
    assert detection.bbox.center.y == 120.0
    assert detection.bbox.size_x == 100.0
    assert detection.bbox.size_y == 200.0


def test_build_detection_clips_bbox_to_image_and_sets_header():
    from std_msgs.msg import Header

    header = Header()
    header.frame_id = "camera_color_optical_frame"
    detection = build_detection(
        bbox=(-10, -5, 700, 500), name="alice", score=0.9, header=header, image_shape=(480, 640)
    )

    assert detection.header.frame_id == "camera_color_optical_frame"
    assert detection.tracking_id == ""  # reservado a rastreio; o nome vai em results[0].id
    assert detection.bbox.center.x == 320.0
    assert detection.bbox.center.y == 240.0
    assert detection.bbox.size_x == 640.0
    assert detection.bbox.size_y == 480.0


def test_build_detection_without_shape_keeps_bbox():
    detection = build_detection(bbox=(-10, 0, 20, 30), name=None, score=0.1)
    assert detection.bbox.size_x == 30.0


def test_clip_bbox_orders_corners_and_flags_outside_boxes():
    from face_recognition_ros.message_builder import bbox_area, clip_bbox

    assert clip_bbox((50, 10, 20, 50), None) == (20, 10, 50, 50)
    outside = clip_bbox((700, 10, 800, 50), (480, 640))
    assert bbox_area(outside) == 0
