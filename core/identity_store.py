import json
from pathlib import Path

import numpy as np


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


class IdentityStore:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.embeddings: dict[str, list[np.ndarray]] = {}

    def enroll(self, name: str, embeddings: list[np.ndarray]) -> None:
        self.embeddings.setdefault(name, []).extend(embeddings)

    def match(self, embedding: np.ndarray, threshold: float) -> tuple[str | None, float]:
        best_name = None
        best_score = 0.0
        for name, known_embeddings in self.embeddings.items():
            for known in known_embeddings:
                score = cosine_similarity(embedding, known)
                if score > best_score:
                    best_name, best_score = name, score
        if best_score >= threshold:
            return best_name, best_score
        return None, best_score

    def save(self) -> None:
        names = []
        arrays = []
        counts = {}
        for name, embs in self.embeddings.items():
            counts[name] = len(embs)
            for emb in embs:
                names.append(name)
                arrays.append(emb)

        npz_path = self.db_path.with_suffix(".npz")
        json_path = self.db_path.with_suffix(".json")
        npz_path.parent.mkdir(parents=True, exist_ok=True)
        if arrays:
            np.savez(npz_path, names=np.array(names), embeddings=np.stack(arrays))
        else:
            np.savez(npz_path, names=np.array([]), embeddings=np.array([]))
        json_path.write_text(json.dumps({"counts": counts}, indent=2))

    def load(self) -> None:
        npz_path = self.db_path.with_suffix(".npz")
        self.embeddings = {}
        if not npz_path.exists():
            return
        data = np.load(npz_path)
        for name, embedding in zip(data["names"], data["embeddings"]):
            self.embeddings.setdefault(str(name), []).append(embedding)
