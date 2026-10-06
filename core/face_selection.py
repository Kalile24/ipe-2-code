from __future__ import annotations

from typing import Optional, Protocol, Sequence


class HasBBox(Protocol):
    bbox: tuple[int, int, int, int]


def bbox_area(bbox: tuple[int, int, int, int]) -> int:
    x1, y1, x2, y2 = bbox
    return max(0, x2 - x1) * max(0, y2 - y1)


def select_reference_face(faces: Sequence[HasBBox], strict: bool = False) -> Optional[HasBBox]:
    """Escolhe qual rosto de uma foto de referência vira embedding no cadastro.

    O detector (SCRFD) devolve os rostos ordenados por confiança, não por tamanho —
    `faces[0]` numa foto de grupo pode ser um figurante nítido ao fundo. Aqui vale o
    maior rosto: em foto de referência, a pessoa cadastrada é quem está em primeiro
    plano. Com `strict=True`, foto com mais de um rosto é recusada (retorna None) —
    mais seguro quando o cadastro é de uma autoridade e o erro custa caro.
    """
    if not faces:
        return None
    if len(faces) > 1 and strict:
        return None
    return max(faces, key=lambda face: bbox_area(face.bbox))
