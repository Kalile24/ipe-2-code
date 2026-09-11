from pathlib import Path

import cv2

from core.config import DB_PATH, DET_SIZE, KNOWN_FACES_DIR
from core.face_engine import FaceEngine
from core.identity_store import IdentityStore


def enroll_from_directory(known_faces_dir: Path, engine: FaceEngine, store: IdentityStore) -> None:
    for person_dir in sorted(known_faces_dir.iterdir()):
        if not person_dir.is_dir():
            continue
        name = person_dir.name
        embeddings = []
        for photo_path in sorted(person_dir.glob("*")):
            frame = cv2.imread(str(photo_path))
            if frame is None:
                print(f"Aviso: não foi possível ler {photo_path}, pulando.")
                continue
            faces = engine.extract_faces(frame)
            if not faces:
                print(f"Aviso: nenhum rosto detectado em {photo_path}, pulando.")
                continue
            embeddings.append(faces[0].embedding)
        if embeddings:
            store.enroll(name, embeddings)
            print(f"{name}: {len(embeddings)} foto(s) cadastrada(s).")


def main() -> None:
    engine = FaceEngine(det_size=DET_SIZE)
    store = IdentityStore(DB_PATH)
    store.load()
    enroll_from_directory(Path(KNOWN_FACES_DIR), engine, store)
    store.save()


if __name__ == "__main__":
    main()
