from types import SimpleNamespace

from core.face_selection import bbox_area, select_reference_face


def _face(x1, y1, x2, y2, det_score=0.9):
    return SimpleNamespace(bbox=(x1, y1, x2, y2), det_score=det_score)


def test_empty_returns_none():
    assert select_reference_face([]) is None


def test_single_face_is_returned():
    face = _face(0, 0, 10, 10)
    assert select_reference_face([face]) is face


def test_prefers_largest_face_not_first_or_most_confident():
    # Ordem do detector = confiança: o primeiro é um rosto pequeno e nítido ao fundo.
    background = _face(0, 0, 20, 20, det_score=0.99)
    foreground = _face(100, 100, 300, 340, det_score=0.80)
    assert select_reference_face([background, foreground]) is foreground


def test_strict_rejects_photo_with_several_faces():
    faces = [_face(0, 0, 20, 20), _face(100, 100, 300, 340)]
    assert select_reference_face(faces, strict=True) is None


def test_strict_still_accepts_single_face():
    face = _face(0, 0, 20, 20)
    assert select_reference_face([face], strict=True) is face


def test_bbox_area_clamps_degenerate_boxes():
    assert bbox_area((10, 10, 5, 20)) == 0
    assert bbox_area((0, 0, 4, 5)) == 20
