import cv2
import insightface.data

from apps.enroll import enroll_from_directory
from core.face_engine import FaceEngine
from core.identity_store import IdentityStore


def test_enroll_from_directory_reads_photos_and_stores_embeddings(tmp_path):
    img = insightface.data.get_image("t1")
    person_dir = tmp_path / "pessoa_teste"
    person_dir.mkdir()
    cv2.imwrite(str(person_dir / "foto1.jpg"), img)

    engine = FaceEngine()
    store = IdentityStore(db_path=str(tmp_path / "db"))

    enroll_from_directory(tmp_path, engine, store)

    assert "pessoa_teste" in store.embeddings
    assert len(store.embeddings["pessoa_teste"]) == 1
    assert store.embeddings["pessoa_teste"][0].shape == (512,)
