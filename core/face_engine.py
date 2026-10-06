from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from insightface.app import FaceAnalysis


@dataclass
class FaceResult:
    bbox: tuple[int, int, int, int]
    embedding: np.ndarray
    det_score: float


class FaceEngine:
    def __init__(
        self,
        det_size: tuple[int, int] = (640, 640),
        model_name: str = "buffalo_l",
        model_root: str | None = None,
    ):
        # O InsightFace baixa o pacote de modelos (~300 MB, GitHub releases) AO INSTANCIAR
        # FaceAnalysis — não no prepare() — e só se `<root>/models/<model_name>/` não existir.
        # Não há variável de ambiente; o único controle é `root=`. No robô (sem internet)
        # o diretório precisa existir de antemão: ver docker/ros2.Dockerfile.
        kwargs = {"root": model_root} if model_root else {}
        self._app = FaceAnalysis(name=model_name, allowed_modules=["detection", "recognition"], **kwargs)
        self._app.prepare(ctx_id=0, det_size=det_size)

    def extract_faces(self, frame: np.ndarray) -> list[FaceResult]:
        faces = self._app.get(frame)
        return [
            FaceResult(
                bbox=tuple(int(v) for v in face.bbox),
                embedding=face.normed_embedding,
                det_score=float(face.det_score),
            )
            for face in faces
        ]
