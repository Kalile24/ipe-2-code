from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class CalibrationResult:
    genuine: list[float] = field(default_factory=list)   # probe vs. a própria identidade
    impostor: list[float] = field(default_factory=list)  # probe vs. as outras identidades
    skipped: list[str] = field(default_factory=list)     # identidades com < 2 fotos

    def table(self, thresholds: list[float]) -> list[tuple[float, float, float]]:
        """(limiar, FNMR, FMR) — FNMR: genuínos rejeitados; FMR: impostores aceitos."""
        g = np.asarray(self.genuine)
        i = np.asarray(self.impostor)
        rows = []
        for t in thresholds:
            fnmr = float((g < t).mean()) if g.size else float("nan")
            fmr = float((i >= t).mean()) if i.size else float("nan")
            rows.append((t, fnmr, fmr))
        return rows

    def safe_interval(self) -> tuple[float, float] | None:
        """(maior impostor, menor genuíno): qualquer limiar aí dentro dá FMR = FNMR = 0
        NESTA amostra. None se as distribuições se sobrepõem."""
        if not self.genuine or not self.impostor:
            return None
        lo, hi = max(self.impostor), min(self.genuine)
        return (lo, hi) if lo < hi else None

    def suggest(self) -> float | None:
        """Ponto médio do intervalo seguro — fica igualmente longe do pior impostor e do
        pior genuíno, que é o que se quer com poucos dados. None se há sobreposição."""
        iv = self.safe_interval()
        return None if iv is None else round((iv[0] + iv[1]) / 2, 2)


def _unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v)


def leave_one_out(embeddings: dict[str, list[np.ndarray]]) -> CalibrationResult:
    """Calibração sem fotos novas: cada foto cadastrada vira consulta contra o banco
    SEM ela (leave-one-out), com centroide normalizado por identidade — o mesmo
    critério que o IdentityStore usa em produção.

    Com poucas pessoas/fotos os números são grosseiros (poucos pares impostores);
    o relatório imprime as contagens para o leitor julgar."""
    res = CalibrationResult()
    names = sorted(embeddings)
    unit = {n: [_unit(np.asarray(e, dtype=np.float64)) for e in embeddings[n]] for n in names}
    centroid_full = {n: _unit(np.mean(np.stack(unit[n]), axis=0)) for n in names}
    for n in names:
        if len(unit[n]) < 2:
            res.skipped.append(n)
            continue
        for k, probe in enumerate(unit[n]):
            rest = [e for j, e in enumerate(unit[n]) if j != k]
            own = float(_unit(np.mean(np.stack(rest), axis=0)) @ probe)
            res.genuine.append(own)
            res.impostor.extend(float(centroid_full[m] @ probe) for m in names if m != n)
    return res
