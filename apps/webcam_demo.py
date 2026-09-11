import argparse

import cv2

from core.config import (
    CAMERA_INDEX,
    DB_PATH,
    DET_SIZE,
    RECOGNITION_INTERVAL_FRAMES,
    SIMILARITY_THRESHOLD,
)
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
    if not store.embeddings:
        print(f"Aviso: nenhuma identidade cadastrada em {DB_PATH}; todos os rostos serão marcados como Desconhecido.")

    cap = cv2.VideoCapture(source)
    if isinstance(source, int):
        # MJPG (comprimido) é mais confiável que o YUYV bruto padrão em
        # links USB mais frágeis — inclui passagens virtuais como o
        # usbipd-win (WSL), onde o bruto costuma chegar corrompido.
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        # Buffer mínimo: sem isso, os ~900ms do reconhecimento acumulam
        # frames atrasados, e o vídeo passa a exibir passado, não o presente.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not cap.isOpened():
        raise SystemExit(f"Não foi possível abrir a fonte de vídeo: {source}")

    print("Pressione 'q' para sair.")
    frame_count = 0
    labeled_boxes: list[tuple[tuple[int, int, int, int], str]] = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break

        if frame_count % RECOGNITION_INTERVAL_FRAMES == 0:
            # Reconhecimento (lento em CPU): roda de vez em quando. Nos
            # frames intermediários não chamamos o modelo — só redesenhamos
            # a última caixa conhecida, o que mantém o vídeo em si fluido.
            labeled_boxes = []
            for face in engine.extract_faces(frame):
                name, score = store.match(face.embedding, SIMILARITY_THRESHOLD)
                label = f"{name} ({score:.2f})" if name else "Desconhecido"
                labeled_boxes.append((face.bbox, label))
        frame_count += 1

        for bbox, label in labeled_boxes:
            x1, y1, x2, y2 = bbox
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
