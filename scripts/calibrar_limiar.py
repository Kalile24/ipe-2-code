"""Calibra SIMILARITY_THRESHOLD a partir do banco já cadastrado.

Uso:
    python -m scripts.calibrar_limiar                 # banco do modelo padrão (core.config)
    python -m scripts.calibrar_limiar --model buffalo_sc

Não precisa de câmera nem de modelo: usa os embeddings salvos por `apps.enroll`
(leave-one-out). Para uma calibração de verdade, cadastre >= 3 fotos por pessoa, em
condições parecidas com as do robô (distância, luz, ângulo), e inclua pessoas que
NÃO devem ser reconhecidas — são elas que medem o falso positivo.
"""
from __future__ import annotations

import argparse

import numpy as np

from core.calibration import leave_one_out
from core.config import DB_PATH, MODEL_NAME, SIMILARITY_THRESHOLD
from core.identity_store import IdentityStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default=MODEL_NAME)
    args = parser.parse_args()

    store = IdentityStore(DB_PATH, model_name=args.model)
    store.load()
    if not store.embeddings:
        raise SystemExit(f"Banco vazio em {store.db_path}. Rode `python -m apps.enroll` antes.")

    res = leave_one_out(store.embeddings)
    n_people = len(store.embeddings)
    print(f"Identidades: {n_people} · fotos: {sum(len(v) for v in store.embeddings.values())} "
          f"· pares genuínos: {len(res.genuine)} · pares impostores: {len(res.impostor)}")
    if res.skipped:
        print(f"Sem calibração (1 foto só): {', '.join(res.skipped)}")
    if n_people < 2 or not res.genuine:
        raise SystemExit("Precisa de >= 2 identidades e >= 1 pessoa com >= 2 fotos para medir algo.")

    thresholds = [round(t, 2) for t in np.arange(0.20, 0.71, 0.05)]
    print("\n limiar   FNMR(genuíno rejeitado)   FMR(impostor aceito)")
    for t, fnmr, fmr in res.table(thresholds):
        mark = "  <- atual" if abs(t - SIMILARITY_THRESHOLD) < 1e-9 else ""
        print(f"  {t:.2f}         {fnmr:6.1%}                 {fmr:6.1%}{mark}")

    g, i = np.asarray(res.genuine), np.asarray(res.impostor)
    print(f"\nGenuínos: min {g.min():.2f} · mediana {np.median(g):.2f} · max {g.max():.2f}")
    if i.size:
        print(f"Impostores: min {i.min():.2f} · mediana {np.median(i):.2f} · max {i.max():.2f}")

    iv = res.safe_interval()
    if iv is None:
        print("\nGenuínos e impostores se SOBREPÕEM nesta amostra: não há limiar sem erro. "
              "Mais/melhores fotos antes de confiar no sistema.")
    else:
        print(f"\nIntervalo sem erro nesta amostra: ({iv[0]:.2f}, {iv[1]:.2f}). "
              f"Sugestão: SIMILARITY_THRESHOLD = {res.suggest():.2f} (ponto médio). "
              f"Com {len(res.impostor)} pares impostores, FMR abaixo de {1/len(res.impostor):.1%} não é mensurável — "
              "cadastre também pessoas que NÃO devem ser reconhecidas.")


if __name__ == "__main__":
    main()
