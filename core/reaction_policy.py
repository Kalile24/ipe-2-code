"""Decide a quem o robô reage: mapa pessoa → gesto, confirmação por frames seguidos e cooldowns.

Puro (sem ROS, sem SDK da Unitree): os nós de `robot_reaction_ros` são cascas em volta disto.
Spec: docs/superpowers/specs/2026-10-21-robot-reaction-design.md
"""
from __future__ import annotations

# Cópia do `action_map` do unitree_sdk2py 1.0.1 (unitree_sdk2py/g1/arm/g1_arm_action_client.py),
# a versão instalada no PC2 do robô. Copiado para validar o mapa onde o SDK não existe (notebook,
# Docker). Se a Unitree mudar os ids, atualize aqui.
GESTOS = {
    "release arm": 99,
    "two-hand kiss": 11,
    "left kiss": 12,
    "right kiss": 13,
    "hands up": 15,
    "clap": 17,
    "high five": 18,
    "hug": 19,
    "heart": 20,
    "right heart": 21,
    "reject": 22,
    "right hand up": 23,
    "x-ray": 24,
    "face wave": 25,
    "high wave": 26,
    "shake hand": 27,
}
RELEASE_ARM = "release arm"
DESCONHECIDO = "desconhecido"  # nome que o face_recognition_node usa abaixo do limiar
_CHAVES_PESSOA = {"gesto"}  # `fala` entra quando houver áudio


class ReactionConfigError(ValueError):
    """Mapa de reações inválido."""


def load_reactions(raw: object) -> dict[str, str]:
    """Valida o conteúdo do YAML (`nome: {gesto: <nome do gesto>}`) e devolve `nome -> gesto`."""
    if not isinstance(raw, dict):
        raise ReactionConfigError(f"o mapa de reações tem que ser um mapa nome -> {{gesto: ...}}, veio {raw!r}")
    if not raw:
        raise ReactionConfigError("o mapa de reações não tem nenhuma pessoa")
    reactions = {}
    for nome, reacao in raw.items():
        if not isinstance(nome, str) or not nome:
            raise ReactionConfigError(f"nome de pessoa inválido: {nome!r}")
        if not isinstance(reacao, dict):
            raise ReactionConfigError(f"{nome}: esperado um mapa com 'gesto', veio {reacao!r}")
        extras = sorted(set(reacao) - _CHAVES_PESSOA)
        if extras:
            raise ReactionConfigError(f"{nome}: chave desconhecida {extras} (só 'gesto' é aceita)")
        gesto = reacao.get("gesto")
        if gesto is None:
            raise ReactionConfigError(f"{nome}: falta 'gesto'")
        if gesto not in GESTOS:
            raise ReactionConfigError(f"{nome}: gesto desconhecido {gesto!r}; válidos: {sorted(GESTOS)}")
        reactions[nome] = gesto
    return reactions
