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


def test_model_root_is_forwarded_to_insightface(monkeypatch, tmp_path):
    import core.face_engine as fe

    seen = {}

    class FakeFaceAnalysis:
        def __init__(self, name, allowed_modules, **kwargs):
            seen.update(kwargs, name=name)

        def prepare(self, ctx_id, det_size):
            pass

    monkeypatch.setattr(fe, "FaceAnalysis", FakeFaceAnalysis)
    FaceEngine(model_name="buffalo_sc", model_root=str(tmp_path))
    assert seen == {"root": str(tmp_path), "name": "buffalo_sc"}

    seen.clear()
    FaceEngine(model_name="buffalo_sc")
    assert "root" not in seen  # sem model_root, o InsightFace usa o padrão dele
