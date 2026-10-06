from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def _unit(v: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(v))
    if not np.isfinite(norm) or norm == 0.0:
        raise ValueError("embedding com norma zero ou não finita")
    return np.asarray(v, dtype=np.float32) / norm


class IdentityStore:
    """Banco de identidades: embeddings por pessoa + decisão de quem é quem.

    Score por identidade = cosseno entre a consulta e o CENTROIDE normalizado daquela
    pessoa (``aggregation="centroid"``, protocolo de avaliação do próprio InsightFace) — ou o
    máximo sobre as fotos (``aggregation="max"``, comportamento antigo, mantido para
    comparação). O máximo infla a falsa aceitação com o número de fotos e é dominado por uma
    foto ruim; o centroide não. Aceita a melhor identidade se ``score >= threshold``.
    """

    def __init__(self, db_path: str, model_name: str = "buffalo_l", aggregation: str = "centroid"):
        base = Path(db_path)
        if base.name in ("", ".", ".."):
            raise ValueError(f"db_path precisa terminar num nome de arquivo, não em diretório: {db_path!r}")
        self.db_path = base.with_name(f"{base.name}_{model_name}")
        if aggregation not in ("centroid", "max"):
            raise ValueError(f"aggregation deve ser 'centroid' ou 'max', não {aggregation!r}")
        self.aggregation = aggregation
        self.embeddings: dict[str, list[np.ndarray]] = {}

    def enroll(self, name: str, embeddings: list[np.ndarray]) -> None:
        if not embeddings:
            return  # nada a cadastrar; não cria identidade vazia
        self.embeddings.setdefault(name, []).extend(_unit(e) for e in embeddings)

    def scores(self, embedding: np.ndarray) -> dict[str, float]:
        """Score por identidade (cosseno), sem aplicar limiar. Consulta degenerada
        (norma zero/NaN) devolve {} — no nó isso vira "desconhecido", não exceção.
        Recalcula os centroides a cada chamada: com poucas pessoas cadastradas isso é
        desprezível frente à inferência."""
        try:
            q = _unit(embedding)
        except ValueError:
            return {}
        out: dict[str, float] = {}
        for name, embs in self.embeddings.items():
            if not embs:
                continue
            if self.aggregation == "centroid":
                out[name] = float(_unit(np.mean(np.stack(embs), axis=0)) @ q)
            else:
                out[name] = float(max(_unit(e) @ q for e in embs))
        return out

    def match(self, embedding: np.ndarray, threshold: float) -> tuple[str | None, float]:
        """(nome ou None, melhor cosseno). O cosseno é o real (pode ser negativo); com banco
        vazio ou consulta degenerada devolve (None, 0.0)."""
        sc = self.scores(embedding)
        if not sc:
            return None, 0.0
        best_name = max(sc, key=sc.get)
        best = sc[best_name]
        return (best_name if best >= threshold else None), best

    # ---- persistência ---------------------------------------------------------------
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
        """Carrega o banco. Embeddings inválidos (norma zero — bancos antigos não validavam)
        são pulados com aviso; nunca deixa o banco meio carregado."""
        npz_path = self.db_path.with_suffix(".npz")
        if not npz_path.exists():
            self.embeddings = {}
            return
        data = np.load(npz_path)
        loaded: dict[str, list[np.ndarray]] = {}
        skipped = 0
        for name, embedding in zip(data["names"], data["embeddings"]):
            try:
                loaded.setdefault(str(name), []).append(_unit(embedding))
            except ValueError:
                skipped += 1
        self.embeddings = {n: v for n, v in loaded.items() if v}
        if skipped:
            print(f"Aviso: {skipped} embedding(s) inválido(s) ignorado(s) em {npz_path}.", file=sys.stderr)
