"""Estágios da reação a uma pessoa: virar, aproximar, fala e posturas.

Puro. Spec: docs/superpowers/specs/2026-11-04-aproximacao-e-estagios-design.md
"""
from __future__ import annotations

ESTAGIOS = ("virar", "aproximar", "fala", "posturas")


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
