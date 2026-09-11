from dataclasses import dataclass

import numpy as np
from insightface.app import FaceAnalysis


@dataclass
class FaceResult:
    bbox: tuple[int, int, int, int]
    embedding: np.ndarray
    det_score: float


class FaceEngine:
    def __init__(self, det_size: tuple[int, int] = (640, 640)):
        self._app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"])
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
