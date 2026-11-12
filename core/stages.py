"""Estágios da reação a uma pessoa: virar, aproximar, fala, posturas e meia_volta.

Puro. Spec: docs/superpowers/specs/2026-11-04-aproximacao-e-estagios-design.md
"""
from __future__ import annotations

import sys

ESTAGIOS = ("virar", "aproximar", "fala", "posturas", "meia_volta")


def parse_stages(texto: str) -> frozenset[str]:
    """Lê 'virar,fala' em um conjunto de estágios; `aproximar` acrescenta `virar`."""
    nomes = [n.strip() for n in texto.split(",") if n.strip()]
    ruins = [n for n in nomes if n not in ESTAGIOS]
    if not nomes or ruins:
        raise ValueError(f"estágios inválidos {ruins or texto!r}; válidos: {', '.join(ESTAGIOS)}")
    estagios = set(nomes)
    if "aproximar" in estagios:
        estagios.add("virar")
    return frozenset(estagios)


def filter_steps(passos: list[dict], estagios: frozenset[str]) -> list[dict]:
    """Mantém falas se há `fala`, e posturas e pausas se há `posturas`. Não revalida os passos."""
    return [p for p in passos if ("fala" in p and "fala" in estagios) or ("fala" not in p and "posturas" in estagios)]


def migrar_estagios(valores: dict) -> dict:
    """Cópia dos valores salvos; arquivo antigo (sem `vyaw_meia_volta`) ganha `meia_volta` em `estagios`."""
    novos = dict(valores)
    if "estagios" in novos and "vyaw_meia_volta" not in novos:
        nomes = [n.strip() for n in str(novos["estagios"]).split(",") if n.strip()]
        if "meia_volta" not in nomes:
            novos["estagios"] = ",".join(nomes + ["meia_volta"])
    return novos


def override_estagios(valores: dict) -> str | None:
    """Lista de `estagios` migrada para sobrescrever o arquivo, ou None se não precisa."""
    novo = migrar_estagios(valores).get("estagios")
    return novo if novo != valores.get("estagios") else None


def main(argv: list[str] | None = None) -> int:
    """`python3 -m core.stages arquivo.yaml`: imprime a lista migrada, ou nada. Nunca atrapalha a partida."""
    argv = sys.argv[1:] if argv is None else argv
    try:
        import yaml

        with open(argv[0]) as f:
            valores = (yaml.safe_load(f) or {}).get("/**", {}).get("ros__parameters", {})
        lista = override_estagios(valores)
        if lista:
            print(lista)
    except Exception:  # arquivo ausente ou ilegível: sem sobrescrita
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
