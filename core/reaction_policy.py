"""Decide a quem o robô reage: mapa pessoa → reação, confirmação por frames seguidos e cooldowns.

Reação = uma rotina de posturas militares, falas e pausas (`passos`), executada pelo body_node
com robot_reaction_ros/g1_arm_controller.py.

Puro (sem ROS, sem SDK da Unitree): os nós de `robot_reaction_ros` são cascas em volta disto.
Specs: docs/superpowers/specs/2026-10-21-robot-reaction-design.md (confirmação e cooldowns) e
2026-10-29-rotina-cumprimento-design.md (rotinas).
"""
from __future__ import annotations

DESCONHECIDO = "desconhecido"  # nome que o face_recognition_node usa abaixo do limiar
# Posturas militares (as do ~/hhhh/movimentos_militares.py) que o body_node sabe executar.
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


def load_reactions(raw: object) -> dict[str, list[dict[str, str]]]:
    """Valida o conteúdo do YAML e devolve `nome -> passos`. Cada pessoa é `{passos: [...]}`."""
    if not isinstance(raw, dict):
        raise ReactionConfigError(f"o mapa de reações tem que ser um mapa nome -> {{passos: [...]}}, veio {raw!r}")
    if not raw:
        raise ReactionConfigError("o mapa de reações não tem nenhuma pessoa")
    reactions = {}
    for nome, reacao in raw.items():
        if not isinstance(nome, str) or not nome:
            raise ReactionConfigError(f"nome de pessoa inválido: {nome!r}")
        if nome == DESCONHECIDO:
            raise ReactionConfigError(f"{DESCONHECIDO!r} não pode estar no mapa: o robô reagiria a qualquer estranho")
        if not isinstance(reacao, dict) or set(reacao) != {"passos"}:
            raise ReactionConfigError(f"{nome}: esperado um mapa com só a chave 'passos', veio {reacao!r}")
        reactions[nome] = validate_steps(nome, reacao["passos"])
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
        reactions: dict[str, list[dict[str, str]]],
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

    def update(
        self, seen: list[tuple[str, float]], now: float, allow_fire: bool = True
    ) -> tuple[str, list[dict[str, str]]] | None:
        """`allow_fire=False` (uma rotina já está em andamento): só acompanha quem está na frente."""
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

        if not allow_fire or (self._last_any is not None and now - self._last_any < self._global_cooldown_s):
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

    def now(self, seen: list[tuple[str, float]], agora: float) -> tuple[str, list[dict[str, str]]] | None:
        """Cumprimentar agora (comando do operador): a pessoa do mapa de maior nota em `seen`, sem
        confirmação nem cooldown. Conta como cumprimentada, como um disparo normal."""
        mapeados = [(score, nome) for nome, score in seen if nome in self._reactions]
        if not mapeados:
            return None
        _, nome = max(mapeados)
        self._last_fired[nome] = self._last_seen[nome] = self._last_any = agora
        self._left[nome] = False
        return nome, self._reactions[nome]

    def forget(self, nome: str) -> None:
        """A reação a `nome` não aconteceu (ninguém para executar, rotina recusada): ele volta a
        poder ser cumprimentado sem esperar o cooldown nem sair da frente. O cooldown global
        continua, para não insistir a cada frame."""
        self._last_fired.pop(nome, None)
        self._left.pop(nome, None)

    def release(self, nome: str | None = None) -> None:
        """Libera a reação de `nome` (None = todos), sem esperar cooldown nem saída da frente."""
        if nome is not None and nome not in self._reactions:
            raise KeyError(f"{nome!r} não está no mapa de reações; nomes: {sorted(self._reactions)}")
        for n in [nome] if nome is not None else list(self._last_fired):
            self._last_fired.pop(n, None)
            self._left.pop(n, None)
        self._last_any = None
