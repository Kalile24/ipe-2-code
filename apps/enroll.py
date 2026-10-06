from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from core.config import DB_PATH, DET_SIZE, KNOWN_FACES_DIR, MODEL_NAME, MODEL_ROOT
from core.face_engine import FaceEngine
from core.face_selection import select_reference_face
from core.identity_store import IdentityStore


def enroll_from_directory(
    known_faces_dir: Path, engine: FaceEngine, store: IdentityStore, strict: bool = False
) -> None:
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
            face = select_reference_face(faces, strict=strict)
            if face is None:
                print(f"Aviso: {len(faces)} rostos em {photo_path} e --strict ativo, pulando.")
                continue
            if len(faces) > 1:
                print(
                    f"Aviso: {len(faces)} rostos em {photo_path}; cadastrando o maior. "
                    "Prefira fotos com uma pessoa só (ou use --strict)."
                )
            embeddings.append(face.embedding)
        if embeddings:
            store.enroll(name, embeddings)
            print(f"{name}: {len(embeddings)} foto(s) cadastrada(s).")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        default=MODEL_NAME,
        help="Pacote de modelo do InsightFace (ex: buffalo_l, buffalo_s, buffalo_sc)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Recusar fotos com mais de um rosto em vez de cadastrar o maior",
    )
    parser.add_argument(
        "--model-root",
        default=MODEL_ROOT,
        help="Pasta raiz dos modelos do InsightFace (default ~/.insightface); use uma pré-carregada quando não houver internet",
    )
    args = parser.parse_args()

    engine = FaceEngine(det_size=DET_SIZE, model_name=args.model, model_root=args.model_root)
    store = IdentityStore(DB_PATH, model_name=args.model)
    enroll_from_directory(Path(KNOWN_FACES_DIR), engine, store, strict=args.strict)
    if not store.embeddings:
        print(f"Aviso: nenhuma pessoa foi cadastrada a partir de {KNOWN_FACES_DIR}.")
    store.save()


if __name__ == "__main__":
    main()
