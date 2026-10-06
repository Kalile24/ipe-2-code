import cv2
import insightface.data

import numpy as np

from apps.enroll import enroll_from_directory
from core.face_engine import FaceEngine
from core.face_selection import bbox_area
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


def test_enroll_group_photo_stores_the_largest_face(tmp_path):
    # t1 tem 6 rostos e o primeiro devolvido pelo detector NÃO é o maior: este teste
    # falharia com o `faces[0]` antigo.
    img = insightface.data.get_image("t1")
    person_dir = tmp_path / "grupo"
    person_dir.mkdir()
    cv2.imwrite(str(person_dir / "foto1.jpg"), img)
    engine = FaceEngine()
    faces = engine.extract_faces(img)
    assert len(faces) > 1
    largest = max(faces, key=lambda f: bbox_area(f.bbox))
    assert faces[0] is not largest

    store = IdentityStore(db_path=str(tmp_path / "db"))
    enroll_from_directory(tmp_path, engine, store)

    # a foto é regravada em JPEG antes do cadastro, então comparamos por cosseno, não byte a byte
    stored = store.embeddings["grupo"][0]
    assert float(stored @ largest.embedding) > 0.98
    assert float(stored @ faces[0].embedding) < 0.5  # não é a pessoa do antigo faces[0]


def test_enroll_strict_skips_group_photo(tmp_path):
    img = insightface.data.get_image("t1")
    person_dir = tmp_path / "grupo"
    person_dir.mkdir()
    cv2.imwrite(str(person_dir / "foto1.jpg"), img)
    store = IdentityStore(db_path=str(tmp_path / "db"))

    enroll_from_directory(tmp_path, FaceEngine(), store, strict=True)

    assert store.embeddings == {}
