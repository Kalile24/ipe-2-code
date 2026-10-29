"""Decide a quem o robô reage: mapa pessoa → reação, confirmação por frames seguidos e cooldowns.

Reação = um gesto pronto do firmware (`gesto`, executado pelo gesture_node) ou uma rotina de
posturas militares e falas (`passos`, executada pelo body_node com o código do ~/hhhh).

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
_CHAVES_PESSOA = {"gesto", "passos"}
# Posturas do ~/hhhh (movimentos_militares.py) que o body_node sabe executar.
POSTURAS = {"sentido", "descansar", "continencia", "desc_arma", "a_vontade"}
A_VONTADE = "a_vontade"  # braços de volta ao equilíbrio e arm_sdk liberado
_TIPOS_PASSO = {"postura", "fala", "pausa"}


class ReactionConfigError(ValueError):
    """Mapa de reações inválido."""


def validate_steps(nome: str, passos: object) -> list[dict[str, str]]:
    """Valida a lista `passos` de uma rotina: cada passo é `{postura: <nome>}`, `{fala: <texto>}`
    ou `{pausa: <segundos>}` (espera extra, ex.: ficar 15 s em descansar).

    Se a rotina mexe os braços, a última postura tem que ser `a_vontade`: é ela que devolve os
    braços ao equilíbrio e solta o arm_sdk; sem isso o braço ficaria preso na última pose.
    """
    if not isinstance(passos, list) or not passos:
        raise ReactionConfigError(f"{nome}: 'passos' tem que ser uma lista não vazia, veio {passos!r}")
    validos = []
    for i, passo in enumerate(passos, start=1):
        if not isinstance(passo, dict) or len(passo) != 1:
            raise ReactionConfigError(f"{nome}: passo {i} tem que ter uma chave só (postura, fala ou pausa), veio {passo!r}")
        ((tipo, valor),) = passo.items()
        if tipo not in _TIPOS_PASSO:
            raise ReactionConfigError(f"{nome}: passo {i} com chave desconhecida {tipo!r}; válidas: {sorted(_TIPOS_PASSO)}")
        if tipo == "postura" and valor not in POSTURAS:
            raise ReactionConfigError(f"{nome}: passo {i}: postura desconhecida {valor!r}; válidas: {sorted(POSTURAS)}")
        if tipo == "fala" and (not isinstance(valor, str) or not valor.strip()):
            raise ReactionConfigError(f"{nome}: passo {i}: fala vazia ou não é texto: {valor!r}")
        # bool é int em Python: `pausa: true` não pode virar 1 s
        if tipo == "pausa" and (isinstance(valor, bool) or not isinstance(valor, (int, float)) or not 0 < valor <= 120):
            raise ReactionConfigError(f"{nome}: passo {i}: pausa tem que ser um número de segundos entre 0 e 120, veio {valor!r}")
        validos.append({tipo: valor})
    posturas = [p["postura"] for p in validos if "postura" in p]
    if posturas and posturas[-1] != A_VONTADE:
        raise ReactionConfigError(f"{nome}: a última postura tem que ser {A_VONTADE!r} (solta os braços), veio {posturas[-1]!r}")
    return validos


def load_reactions(raw: object) -> dict[str, str | list[dict[str, str]]]:
    """Valida o conteúdo do YAML e devolve `nome -> gesto` (str) ou `nome -> passos` (lista).

    Cada pessoa tem exatamente um de: `gesto: <nome do gesto>` ou `passos: [...]`.
    """
    if not isinstance(raw, dict):
        raise ReactionConfigError(f"o mapa de reações tem que ser um mapa nome -> {{gesto|passos: ...}}, veio {raw!r}")
    if not raw:
        raise ReactionConfigError("o mapa de reações não tem nenhuma pessoa")
    reactions = {}
    for nome, reacao in raw.items():
        if not isinstance(nome, str) or not nome:
            raise ReactionConfigError(f"nome de pessoa inválido: {nome!r}")
        if nome == DESCONHECIDO:
            raise ReactionConfigError(f"{DESCONHECIDO!r} não pode estar no mapa: o robô reagiria a qualquer estranho")
        if not isinstance(reacao, dict):
            raise ReactionConfigError(f"{nome}: esperado um mapa com 'gesto' ou 'passos', veio {reacao!r}")
        extras = sorted(set(reacao) - _CHAVES_PESSOA)
        if extras:
            raise ReactionConfigError(f"{nome}: chave desconhecida {extras} (só 'gesto' ou 'passos')")
        if len(reacao) != 1:
            raise ReactionConfigError(f"{nome}: falta 'gesto' ou 'passos' (exatamente um dos dois)")
        if "passos" in reacao:
            reactions[nome] = validate_steps(nome, reacao["passos"])
            continue
        gesto = reacao["gesto"]
        if gesto not in GESTOS:
            raise ReactionConfigError(f"{nome}: gesto desconhecido {gesto!r}; válidos: {sorted(GESTOS)}")
        reactions[nome] = gesto
    return reactions


class ReactionPolicy:
    """Recebe os nomes vistos em cada frame e diz quando reagir.

    - Confirmação: a pessoa precisa estar em `confirm_frames` frames seguidos; um frame sem ela
      (inclusive vazio) zera a contagem.
    - Repetição: depois de reagir a uma pessoa, só reage a ela de novo quando as DUAS valerem:
      passaram `person_cooldown_s` desde a reação E ela saiu da frente da câmera por
      `absence_s` seguidos nesse meio-tempo. Quem fica parado na frente não é cumprimentado de
      novo; a ausência curta evita que uma falha do reconhecimento (rosto virado) conte como saída.
    - `global_cooldown_s` entre quaisquer duas reações.
    - Várias confirmadas no mesmo frame: só a de maior score; as outras continuam contando.
    - `release()`: o comando manual de teste; a pessoa (ou todas) pode ser cumprimentada já.
    """

    def __init__(
        self,
        reactions: dict[str, str | list[dict[str, str]]],
        confirm_frames: int = 5,
        person_cooldown_s: float = 300.0,
        global_cooldown_s: float = 10.0,
        absence_s: float = 5.0,
    ) -> None:
        if confirm_frames < 1:
            raise ValueError(f"confirm_frames tem que ser >= 1, veio {confirm_frames}")
        self._reactions = reactions
        self._confirm_frames = confirm_frames
        self._person_cooldown_s = person_cooldown_s
        self._global_cooldown_s = global_cooldown_s
        self._absence_s = absence_s
        self._streak: dict[str, int] = {}
        self._last_fired: dict[str, float] = {}
        self._last_seen: dict[str, float] = {}
        self._left: dict[str, bool] = {}  # saiu da frente desde a última reação?
        self._last_any: float | None = None

    def update(self, seen: list[tuple[str, float]], now: float) -> tuple[str, str | list[dict[str, str]]] | None:
        best: dict[str, float] = {}
        for nome, score in seen:
            if nome in self._reactions:  # `desconhecido` e quem não está no mapa ficam fora
                best[nome] = max(score, best.get(nome, score))
        self._streak = {nome: self._streak.get(nome, 0) + 1 for nome in best}
        for nome in best:
            self._last_seen[nome] = now
        for nome in self._last_fired:
            if nome not in best and now - self._last_seen[nome] >= self._absence_s:
                self._left[nome] = True

        if self._last_any is not None and now - self._last_any < self._global_cooldown_s:
            return None
        prontos = [nome for nome in best if self._streak[nome] >= self._confirm_frames and self._may_repeat(nome, now)]
        if not prontos:
            return None
        nome = max(prontos, key=lambda n: best[n])
        self._last_fired[nome] = now
        self._last_seen[nome] = now
        self._left[nome] = False
        self._last_any = now
        return nome, self._reactions[nome]

    def _may_repeat(self, nome: str, now: float) -> bool:
        if nome not in self._last_fired:
            return True
        return self._left[nome] and now - self._last_fired[nome] >= self._person_cooldown_s

    def release(self, nome: str | None = None) -> None:
        """Libera a reação de `nome` (None = todos), sem esperar cooldown nem saída da frente."""
        if nome is not None and nome not in self._reactions:
            raise KeyError(f"{nome!r} não está no mapa de reações; nomes: {sorted(self._reactions)}")
        for n in [nome] if nome is not None else list(self._last_fired):
            self._last_fired.pop(n, None)
            self._left.pop(n, None)
        self._last_any = None
