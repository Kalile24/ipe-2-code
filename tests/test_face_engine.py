import insightface.data

from core.face_engine import FaceEngine, FaceResult


def test_extract_faces_detects_faces_in_sample_image():
    # Bundled with the insightface package itself — no need to version
    # a photo of a real person in this repo.
    img = insightface.data.get_image("t1")
    engine = FaceEngine()

    faces = engine.extract_faces(img)

    assert len(faces) >= 1
    face = faces[0]
    assert isinstance(face, FaceResult)
    assert face.embedding.shape == (512,)
    assert 0.0 <= face.det_score <= 1.0
    assert len(face.bbox) == 4
