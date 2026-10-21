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
        if nome == DESCONHECIDO:
            raise ReactionConfigError(f"{DESCONHECIDO!r} não pode estar no mapa: o robô reagiria a qualquer estranho")
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


class ReactionPolicy:
    """Recebe os nomes vistos em cada frame e diz quando reagir.

    - Confirmação: a pessoa precisa estar em `confirm_frames` frames seguidos; um frame sem ela
      (inclusive vazio) zera a contagem.
    - Cooldowns contados do disparo: `person_cooldown_s` para a mesma pessoa e `global_cooldown_s`
      entre quaisquer duas reações.
    - Várias confirmadas no mesmo frame: só a de maior score; as outras continuam contando.
    """

    def __init__(
        self,
        reactions: dict[str, str],
        confirm_frames: int = 5,
        person_cooldown_s: float = 60.0,
        global_cooldown_s: float = 10.0,
    ) -> None:
        if confirm_frames < 1:
            raise ValueError(f"confirm_frames tem que ser >= 1, veio {confirm_frames}")
        self._reactions = reactions
        self._confirm_frames = confirm_frames
        self._person_cooldown_s = person_cooldown_s
        self._global_cooldown_s = global_cooldown_s
        self._streak: dict[str, int] = {}
        self._last_fired: dict[str, float] = {}
        self._last_any: float | None = None

    def update(self, seen: list[tuple[str, float]], now: float) -> tuple[str, str] | None:
        best: dict[str, float] = {}
        for nome, score in seen:
            if nome in self._reactions:  # `desconhecido` e quem não está no mapa ficam fora
                best[nome] = max(score, best.get(nome, score))
        self._streak = {nome: self._streak.get(nome, 0) + 1 for nome in best}

        if self._last_any is not None and now - self._last_any < self._global_cooldown_s:
            return None
        prontos = [
            nome
            for nome in best
            if self._streak[nome] >= self._confirm_frames
            and (nome not in self._last_fired or now - self._last_fired[nome] >= self._person_cooldown_s)
        ]
        if not prontos:
            return None
        nome = max(prontos, key=lambda n: best[n])
        self._last_fired[nome] = now
        self._last_any = now
        return nome, self._reactions[nome]
