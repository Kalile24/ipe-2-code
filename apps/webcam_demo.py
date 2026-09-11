import argparse

import cv2

from core.config import CAMERA_INDEX, DB_PATH, DET_SIZE, SIMILARITY_THRESHOLD
from core.face_engine import FaceEngine
from core.identity_store import IdentityStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        default=str(CAMERA_INDEX),
        help="Índice da câmera (ex: 0) ou caminho de um arquivo de vídeo",
    )
    args = parser.parse_args()
    source = int(args.source) if args.source.isdigit() else args.source

    engine = FaceEngine(det_size=DET_SIZE)
    store = IdentityStore(DB_PATH)
    store.load()

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise SystemExit(f"Não foi possível abrir a fonte de vídeo: {source}")

    print("Pressione 'q' para sair.")
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        for face in engine.extract_faces(frame):
            name, score = store.match(face.embedding, SIMILARITY_THRESHOLD)
            label = f"{name} ({score:.2f})" if name else "Desconhecido"
            x1, y1, x2, y2 = face.bbox
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(
                frame,
                label,
                (x1, max(y1 - 10, 0)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
            )
        cv2.imshow("Reconhecimento facial", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
