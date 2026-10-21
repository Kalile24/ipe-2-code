# Reação do robô ao reconhecer uma pessoa — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quando o reconhecimento vê uma pessoa do mapa YAML por alguns frames seguidos, o robô faz o gesto pronto do firmware associado a ela — com o nó de gesto desarmado (dry-run) por padrão.

**Architecture:** Lógica pura (tabela de gestos, validação do mapa, confirmação e cooldowns) em `core/reaction_policy.py`, testada na CI. Pacote ROS2 novo `robot_reaction_ros` com dois nós finos: `reaction_node` (assina `/face_recognition/detections`, publica o nome do gesto em `/reaction/gesture`) e `gesture_node` (único que fala com o firmware via `G1ArmActionClient`, publica eventos em `/reaction/gesture_status`). Um launch de topo inclui o launch do reconhecimento e sobe os dois nós; o `robo_tmux.sh` passa a usá-lo.

**Tech Stack:** Python 3.8, ROS2 Foxy (`rclpy`, `std_msgs`, `std_srvs`, `vision_msgs`, `launch_ros`), PyYAML (vem com o ROS), `unitree_sdk2py` 1.0.1 (só no robô, import tardio), pytest, Docker `face-recognition-ros2:local`.

**Spec:** `docs/superpowers/specs/2026-10-21-robot-reaction-design.md`

## Global Constraints

- Todo módulo `.py` novo começa com `from __future__ import annotations` e só usa sintaxe 3.8 (o `tests/test_future_annotations.py` cobra).
- `core/` nunca importa `rclpy`, mensagens ROS, `yaml` nem `unitree_sdk2py` — a CI pura instala só `numpy pytest`.
- `face_recognition_ros` não muda (nenhum arquivo dele é editado).
- Tópicos: `/face_recognition/detections` (entrada), `/reaction/gesture` e `/reaction/gesture_status` (`std_msgs/String`).
- Padrões: `confirm_frames` = 5, `person_cooldown_s` = 60.0, `global_cooldown_s` = 10.0, `armed` = `false`, `network_interface` = `eth0`, `hold_s` = 2.0, `rpc_timeout_s` = 10.0.
- Status, uma linha por evento, exatamente: `armed`, `disarmed`, `dry_run <gesto>`, `started <gesto>`, `done <gesto>`, `rejected busy`, `rejected unknown '<nome>'`, `failed <gesto> code=<n>`, `failed <gesto> <exceção>`, `failed init <erro>`.
- O `gesture_node` nunca usa `LocoClient`, nunca troca o modo do robô, nunca controla o braço em baixo nível.
- Só `armed` exatamente igual a `True` (bool) arma; qualquer outra coisa (string, int) fica desarmado.
- Nomes de gestos e ids: cópia do `action_map` do `unitree_sdk2py` 1.0.1.
- Commits em inglês, `tipo: descrição`, terminando com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Sem push (o usuário faz).
- Nada é rodado no robô pelo agente: a Task 7 são instruções para o usuário.

## Review Focus

- **A mesma pessoa duas vezes no mesmo frame** (dois rostos casando com `gil`) deve contar como um frame só, não acelerar a confirmação — teste na Task 2.
- **Exceção do SDK no meio do gesto** (em vez de código de erro) não pode deixar o `gesture_node` preso em "ocupado" para sempre, e o `release arm` ainda é tentado — teste na Task 4.
- **Comando vazio ou com espaço** (`""`, `" high wave"`, vindo de um `ros2 topic pub` à mão) deve virar `rejected unknown` visível, nunca um gesto — teste na Task 4.
- **Armar duas vezes, ou armar depois de uma falha de init**, não reinicializa o SDK à toa e permite tentar de novo — testes na Task 4.
- **Arquivo do mapa inexistente** deve derrubar o `reaction_node` na partida com o caminho na mensagem — teste na Task 3.

---

## File Structure

```
core/reaction_policy.py                          # novo: GESTOS, load_reactions, ReactionPolicy (puro)
tests/test_reaction_policy.py                    # novo: testes puros (CI)
tests/test_future_annotations.py                 # modificado: varre o pacote novo
ros2_ws/src/robot_reaction_ros/
├── package.xml                                  # novo
├── setup.py / setup.cfg                         # novos
├── resource/robot_reaction_ros                  # novo (arquivo vazio, índice ament)
├── config/reactions.yaml                        # novo: mapa pessoa → gesto
├── launch/robo.launch.py                        # novo: reconhecimento + reação + gesto
├── robot_reaction_ros/__init__.py               # novo (vazio)
├── robot_reaction_ros/reaction_node.py          # novo
├── robot_reaction_ros/gesture_node.py           # novo
└── test/test_reaction_node.py, test/test_gesture_node.py   # novos (Docker)
scripts/robo_tmux.sh                             # modificado: launch de topo + janela "gestos"
docs/guides/jetson-deployment.md, README.md      # modificados
```

**Como rodar os testes do Docker** (usado nas Tasks 3–5; na raiz do repo, imagem já existe):

```bash
docker run --rm -v "$(pwd)":/workspace -w /workspace face-recognition-ros2:local bash -c \
  "source /opt/ros/foxy/setup.bash && pip install --no-deps -e . >/dev/null && cd ros2_ws \
   && colcon build --symlink-install && source install/setup.bash \
   && colcon test --packages-select robot_reaction_ros --event-handlers console_direct+ \
   && colcon test-result --verbose"
```

Chamado abaixo de **`<docker-test>`**. Para um teste só, troque a parte do `colcon test` por
`python3 -m pytest src/robot_reaction_ros/test/<arquivo>.py::<teste> -v`.

---

### Task 1: Tabela de gestos e validação do mapa

**Files:**
- Create: `core/reaction_policy.py`
- Test: `tests/test_reaction_policy.py`

**Interfaces:**
- Produces: `GESTOS: dict[str, int]`, `RELEASE_ARM = "release arm"`, `DESCONHECIDO = "desconhecido"`, `class ReactionConfigError(ValueError)`, `load_reactions(raw: object) -> dict[str, str]` (nome → gesto).

- [ ] **Step 1: Write the failing test**

`tests/test_reaction_policy.py`:

```python
from __future__ import annotations

import pytest

from core.reaction_policy import GESTOS, RELEASE_ARM, ReactionConfigError, load_reactions


def test_gesture_ids_match_the_sdk_action_map():
    assert GESTOS["high wave"] == 26
    assert GESTOS["shake hand"] == 27
    assert GESTOS[RELEASE_ARM] == 99


def test_valid_map_returns_name_to_gesture():
    raw = {"gil": {"gesto": "high wave"}, "marcos": {"gesto": "shake hand"}}
    assert load_reactions(raw) == {"gil": "high wave", "marcos": "shake hand"}


@pytest.mark.parametrize(
    "raw, trecho",
    [
        (None, "mapa"),  # arquivo YAML vazio
        (["gil"], "mapa"),
        ({}, "nenhuma pessoa"),
        ({"gil": "high wave"}, "gil"),
        ({"gil": {}}, "gesto"),
        ({"gil": {"gesture": "high wave"}}, "gesture"),
        ({"gil": {"gesto": "high wave", "fala": "oi"}}, "fala"),
        ({"gil": {"gesto": "continencia"}}, "continencia"),
        ({1: {"gesto": "high wave"}}, "1"),
    ],
)
def test_invalid_maps_fail_naming_the_problem(raw, trecho):
    with pytest.raises(ReactionConfigError, match=trecho):
        load_reactions(raw)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_reaction_policy.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'core.reaction_policy'`

- [ ] **Step 3: Write minimal implementation**

`core/reaction_policy.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_reaction_policy.py -v`
Expected: PASS (11 testes)

- [ ] **Step 5: Commit**

```bash
git add core/reaction_policy.py tests/test_reaction_policy.py
git commit -m "feat: add the gesture table and reaction map validation"
```

---

### Task 2: Política de confirmação e cooldowns

**Files:**
- Modify: `core/reaction_policy.py` (acrescentar no fim)
- Test: `tests/test_reaction_policy.py` (acrescentar no fim)

**Interfaces:**
- Consumes: `load_reactions` (Task 1) — a política recebe o dict já validado.
- Produces: `class ReactionPolicy(reactions: dict[str, str], confirm_frames: int = 5, person_cooldown_s: float = 60.0, global_cooldown_s: float = 10.0)` com `update(seen: list[tuple[str, float]], now: float) -> tuple[str, str] | None` — recebe `(nome, score)` das detecções de **um** frame e o instante; devolve `(nome, gesto)` a quem reagir ou `None`.

- [ ] **Step 1: Write the failing test**

Acrescentar a `tests/test_reaction_policy.py` (e `ReactionPolicy` no import do topo):

```python
from core.reaction_policy import ReactionPolicy

REACOES = {"gil": "high wave", "marcos": "shake hand"}
GIL = [("gil", 0.8)]
MARCOS = [("marcos", 0.8)]


def _policy():
    return ReactionPolicy(REACOES, confirm_frames=3, person_cooldown_s=60.0, global_cooldown_s=10.0)


def _feed(policy, frames, start=0.0):
    """Um frame por segundo a partir de `start` (tempos inteiros: sem erro de ponto flutuante)."""
    return [policy.update(seen, start + i) for i, seen in enumerate(frames)]


def test_fires_only_after_n_consecutive_frames():
    assert _feed(_policy(), [GIL] * 3) == [None, None, ("gil", "high wave")]


def test_a_frame_without_the_person_resets_the_count():
    assert _feed(_policy(), [GIL, GIL, [], GIL, GIL]) == [None] * 5


def test_unknown_and_unmapped_people_never_fire():
    assert _feed(_policy(), [[("desconhecido", 0.3), ("ze_batista", 0.9)]] * 10) == [None] * 10


def test_same_person_twice_in_one_frame_counts_once():
    assert _feed(_policy(), [[("gil", 0.6), ("gil", 0.7)]] * 2) == [None, None]


def test_person_cooldown_blocks_until_it_expires():
    p = _policy()
    assert _feed(p, [GIL] * 3)[-1] == ("gil", "high wave")  # disparo em t=2
    assert p.update(GIL, 61.0) is None  # ainda na frente, dentro dos 60 s
    assert p.update(GIL, 62.0) == ("gil", "high wave")


def test_global_cooldown_blocks_another_person():
    p = _policy()
    assert _feed(p, [GIL] * 3)[-1] == ("gil", "high wave")  # disparo em t=2
    assert _feed(p, [MARCOS] * 4, start=3.0) == [None] * 4  # confirmado em t=5, mas global até t=12
    assert p.update(MARCOS, 12.0) == ("marcos", "shake hand")


def test_two_confirmed_in_same_frame_highest_score_wins_and_other_waits():
    p = _policy()
    ambos = [("gil", 0.6), ("marcos", 0.9)]
    assert _feed(p, [ambos] * 3) == [None, None, ("marcos", "shake hand")]
    assert p.update(ambos, 12.0) == ("gil", "high wave")


def test_confirm_frames_must_be_positive():
    with pytest.raises(ValueError):
        ReactionPolicy(REACOES, confirm_frames=0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_reaction_policy.py -v`
Expected: FAIL com `ImportError: cannot import name 'ReactionPolicy'`

- [ ] **Step 3: Write minimal implementation**

Acrescentar ao fim de `core/reaction_policy.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/ -q --ignore=tests/test_enroll.py --ignore=tests/test_face_engine.py`
Expected: PASS (todos, inclusive os antigos)

- [ ] **Step 5: Commit**

```bash
git add core/reaction_policy.py tests/test_reaction_policy.py
git commit -m "feat: add the reaction policy with confirmation frames and cooldowns"
```

---

### Task 3: Pacote `robot_reaction_ros` e `reaction_node`

**Files:**
- Create: `ros2_ws/src/robot_reaction_ros/package.xml`, `setup.py`, `setup.cfg`, `resource/robot_reaction_ros` (vazio), `robot_reaction_ros/__init__.py` (vazio), `robot_reaction_ros/reaction_node.py`, `config/reactions.yaml`, `launch/.gitkeep` (vazio — a pasta precisa existir para o `setup.py` até a Task 5)
- Modify: `tests/test_future_annotations.py:5-10` (lista `SOURCE_DIRS`)
- Test: `ros2_ws/src/robot_reaction_ros/test/test_reaction_node.py`

**Interfaces:**
- Consumes: `load_reactions`, `ReactionConfigError`, `ReactionPolicy` (Tasks 1–2).
- Produces: nó `reaction_node` (classe `ReactionNode`, atributo `_publisher` de `std_msgs/String` em `/reaction/gesture`, callback `_on_detections(msg: Detection2DArray)`); parâmetros `reactions_file` (`""` = o `config/reactions.yaml` instalado), `detections_topic`, `confirm_frames`, `person_cooldown_s`, `global_cooldown_s`; executável `reaction_node`.

- [ ] **Step 1: Esqueleto do pacote**

`ros2_ws/src/robot_reaction_ros/package.xml`:

```xml
<?xml version="1.0"?>
<package format="3">
  <name>robot_reaction_ros</name>
  <version>0.1.0</version>
  <description>Reação do Unitree G1 ao reconhecer uma pessoa (gestos do firmware)</description>
  <maintainer email="marcoskmvasconcellos@gmail.com">Marcos Kalile</maintainer>
  <license>Apache-2.0</license>

  <buildtool_depend>ament_python</buildtool_depend>

  <exec_depend>rclpy</exec_depend>
  <exec_depend>std_msgs</exec_depend>
  <exec_depend>std_srvs</exec_depend>
  <exec_depend>vision_msgs</exec_depend>
  <exec_depend>ament_index_python</exec_depend>
  <exec_depend>launch</exec_depend>
  <exec_depend>launch_ros</exec_depend>
  <exec_depend>python3-yaml</exec_depend>
  <!-- só pelo launch de topo, que inclui o launch dele; nenhum import Python -->
  <exec_depend>face_recognition_ros</exec_depend>

  <test_depend>python3-pytest</test_depend>

  <export>
    <build_type>ament_python</build_type>
  </export>
</package>
```

`ros2_ws/src/robot_reaction_ros/setup.py`:

```python
from glob import glob

from setuptools import find_packages, setup

package_name = "robot_reaction_ros"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", glob("launch/*.launch.py")),
        (f"share/{package_name}/config", ["config/reactions.yaml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Marcos Kalile",
    maintainer_email="marcoskmvasconcellos@gmail.com",
    description="Reação do Unitree G1 ao reconhecer uma pessoa (gestos do firmware)",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "reaction_node = robot_reaction_ros.reaction_node:main",
            "gesture_node = robot_reaction_ros.gesture_node:main",
        ],
    },
)
```

`ros2_ws/src/robot_reaction_ros/setup.cfg`:

```ini
[develop]
script_dir=$base/lib/robot_reaction_ros
[install]
install_scripts=$base/lib/robot_reaction_ros
```

`ros2_ws/src/robot_reaction_ros/config/reactions.yaml`:

```yaml
# Quem dispara reação e qual. Nome = o mesmo do cadastro (pasta em data/known_faces/<nome>/).
# Gestos válidos: GESTOS em core/reaction_policy.py (ex.: high wave, face wave, shake hand, clap).
gil:
  gesto: high wave
marcos:
  gesto: shake hand
```

Criar vazios: `resource/robot_reaction_ros`, `robot_reaction_ros/__init__.py`, `launch/.gitkeep`.

Em `tests/test_future_annotations.py`, acrescentar à lista `SOURCE_DIRS`:

```python
    REPO_ROOT / "ros2_ws" / "src" / "robot_reaction_ros" / "robot_reaction_ros",
```

- [ ] **Step 2: Write the failing test**

`ros2_ws/src/robot_reaction_ros/test/test_reaction_node.py`:

```python
"""Testes do reaction_node sem câmera: detecções montadas à mão."""
import pytest
import rclpy
from vision_msgs.msg import Detection2D, Detection2DArray, ObjectHypothesisWithPose

import robot_reaction_ros.reaction_node as node_mod
from core.reaction_policy import ReactionConfigError


def _array(*nomes):
    msg = Detection2DArray()
    for nome in nomes:
        hypothesis = ObjectHypothesisWithPose()
        hypothesis.id = nome
        hypothesis.score = 0.8
        detection = Detection2D()
        detection.results.append(hypothesis)
        msg.detections.append(detection)
    return msg


def _yaml(tmp_path, text):
    path = tmp_path / "reactions.yaml"
    path.write_text(text)
    return path


@pytest.fixture
def node(tmp_path, monkeypatch):
    path = _yaml(tmp_path, "gil:\n  gesto: high wave\n")
    rclpy.init(args=["--ros-args", "-p", f"reactions_file:={path}", "-p", "confirm_frames:=3"])
    n = node_mod.ReactionNode()
    published = []
    monkeypatch.setattr(n._publisher, "publish", published.append)
    yield n, published
    n.destroy_node()
    rclpy.shutdown()


def test_confirmed_person_publishes_one_gesture_command(node):
    n, published = node
    for _ in range(6):
        n._on_detections(_array("gil", "desconhecido"))
    assert [m.data for m in published] == ["high wave"]


def test_empty_arrays_reset_the_count(node):
    n, published = node
    for msg in [_array("gil"), _array("gil"), _array(), _array("gil"), _array("gil")]:
        n._on_detections(msg)
    assert published == []


def _start_must_fail(args, exc, trecho):
    rclpy.init(args=["--ros-args", *args])
    try:
        with pytest.raises(exc, match=trecho):
            node_mod.ReactionNode()
    finally:
        rclpy.shutdown()


def test_invalid_map_stops_the_node_at_startup(tmp_path):
    path = _yaml(tmp_path, "gil:\n  gesture: high wave\n")
    _start_must_fail(["-p", f"reactions_file:={path}"], ReactionConfigError, "gesture")


def test_missing_map_file_fails_with_its_path(tmp_path):
    _start_must_fail(["-p", f"reactions_file:={tmp_path}/nao_existe.yaml"], FileNotFoundError, "nao_existe")


def test_installed_default_map_loads():
    rclpy.init(args=[])
    try:
        n = node_mod.ReactionNode()  # reactions_file "" = config/reactions.yaml do pacote
        n.destroy_node()
    finally:
        rclpy.shutdown()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `<docker-test>`
Expected: FAIL — `ModuleNotFoundError: No module named 'robot_reaction_ros.reaction_node'` (o build passa; o setup.py aponta `gesture_node` para um módulo que ainda não existe, o que só quebra ao rodar o executável, não o build)

- [ ] **Step 4: Write minimal implementation**

`ros2_ws/src/robot_reaction_ros/robot_reaction_ros/reaction_node.py`:

```python
from __future__ import annotations

import os
import time

import rclpy
import yaml
from ament_index_python.packages import get_package_share_directory
from rclpy.node import Node
from rclpy.qos import QoSProfile
from std_msgs.msg import String
from vision_msgs.msg import Detection2DArray

from core.reaction_policy import ReactionPolicy, load_reactions


class ReactionNode(Node):
    """Escuta as detecções e publica em /reaction/gesture o gesto de quem merece reação."""

    def __init__(self) -> None:
        super().__init__("reaction_node")
        self.declare_parameter("reactions_file", "")
        self.declare_parameter("detections_topic", "/face_recognition/detections")
        self.declare_parameter("confirm_frames", 5)
        self.declare_parameter("person_cooldown_s", 60.0)
        self.declare_parameter("global_cooldown_s", 10.0)

        path = self.get_parameter("reactions_file").value or os.path.join(
            get_package_share_directory("robot_reaction_ros"), "config", "reactions.yaml"
        )
        with open(path) as f:  # arquivo ausente ou mapa inválido derrubam o nó na partida
            reactions = load_reactions(yaml.safe_load(f))
        # float()/int(): `-p x:=60` chega como int e `-p x:=5.0` como float
        self._policy = ReactionPolicy(
            reactions,
            confirm_frames=int(self.get_parameter("confirm_frames").value),
            person_cooldown_s=float(self.get_parameter("person_cooldown_s").value),
            global_cooldown_s=float(self.get_parameter("global_cooldown_s").value),
        )

        detections_topic = self.get_parameter("detections_topic").value
        self._publisher = self.create_publisher(String, "/reaction/gesture", 10)
        self._subscription = self.create_subscription(
            Detection2DArray, detections_topic, self._on_detections, QoSProfile(depth=1)
        )
        self.get_logger().info(f"mapa {path}: {reactions}; assinando {detections_topic}")

    def _on_detections(self, msg: Detection2DArray) -> None:
        seen = [(d.results[0].id, d.results[0].score) for d in msg.detections if d.results]
        hit = self._policy.update(seen, time.monotonic())
        if hit is None:
            return
        nome, gesto = hit
        self.get_logger().info(f"reagindo a {nome}: {gesto}")
        self._publisher.publish(String(data=gesto))


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = ReactionNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():  # o Ctrl+C já pode ter desligado o contexto
            rclpy.shutdown()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `<docker-test>` e `PYTHONPATH=. .venv/bin/python -m pytest tests/test_future_annotations.py -v`
Expected: PASS (5 testes no Docker; os 2 do future_annotations)

- [ ] **Step 6: Commit**

```bash
git add ros2_ws/src/robot_reaction_ros tests/test_future_annotations.py
git commit -m "feat: add the robot_reaction_ros package with the reaction node"
```

---

### Task 4: `gesture_node`

**Files:**
- Create: `ros2_ws/src/robot_reaction_ros/robot_reaction_ros/gesture_node.py`
- Test: `ros2_ws/src/robot_reaction_ros/test/test_gesture_node.py`

**Interfaces:**
- Consumes: `GESTOS`, `RELEASE_ARM` (Task 1); executável `gesture_node` já declarado no `setup.py` (Task 3).
- Produces: classe `GestureNode(client_factory: Callable[[str, float], object] = _sdk_client)`; `client_factory(network_interface, rpc_timeout_s)` devolve um objeto com `ExecuteAction(action_id: int) -> int`. Métodos usados pelos testes e pelo `main`: `_publish(text: str)`, `_on_gesture(msg: String)`, `_on_set_armed(request, response)`, `release_if_busy()`, atributo `_worker: threading.Thread | None`. Serviço `~/set_armed` (`std_srvs/SetBool`), tópico `/reaction/gesture_status`.

- [ ] **Step 1: Write the failing test**

`ros2_ws/src/robot_reaction_ros/test/test_gesture_node.py`:

```python
"""Testes do gesture_node sem robô: o cliente do SDK é substituído por um dublê."""
import threading

import pytest
import rclpy
from std_msgs.msg import String
from std_srvs.srv import SetBool

import robot_reaction_ros.gesture_node as node_mod

HIGH_WAVE, RELEASE = 26, 99


class _FakeClient:
    def __init__(self, codes=None, raises=None):
        self.calls = []
        self.codes = codes or {}
        self.raises = raises
        self.gate = None  # threading.Event: segura o gesto em andamento

    def ExecuteAction(self, action_id):
        self.calls.append(action_id)
        if action_id != RELEASE:
            if self.gate is not None:
                self.gate.wait(5)
            if self.raises is not None:
                raise self.raises
        return self.codes.get(action_id, 0)


@pytest.fixture
def make_node(monkeypatch):
    status, inits, nodes = [], [], []
    monkeypatch.setattr(node_mod.GestureNode, "_publish", lambda self, text: status.append(text))

    def make(client=None, factory_error=None, armed=False):
        def factory(network_interface, timeout):
            inits.append((network_interface, timeout))
            if factory_error is not None:
                raise factory_error
            return client

        rclpy.init(args=["--ros-args", "-p", "hold_s:=0.0", "-p", f"armed:={'true' if armed else 'false'}"])
        n = node_mod.GestureNode(client_factory=factory)
        nodes.append(n)
        return n

    yield make, status, inits
    for n in nodes:
        n.destroy_node()
    rclpy.shutdown()


def _arm(n, on=True):
    return n._on_set_armed(SetBool.Request(data=on), SetBool.Response())


def _send(n, gesto, wait=True):
    n._on_gesture(String(data=gesto))
    if wait and n._worker is not None:
        n._worker.join(5)


def test_disarmed_publishes_dry_run_and_never_builds_the_client(make_node):
    make, status, inits = make_node
    _send(make(), "high wave")
    assert status == ["dry_run high wave"]
    assert inits == []


def test_unknown_empty_and_padded_commands_are_rejected(make_node):
    make, status, _ = make_node
    n = make(client=_FakeClient())
    _arm(n)
    for gesto in ["continencia", "", " high wave"]:
        _send(n, gesto)
    assert status == ["armed", "rejected unknown 'continencia'", "rejected unknown ''", "rejected unknown ' high wave'"]


def test_armed_gesture_runs_then_releases(make_node):
    make, status, inits = make_node
    client = _FakeClient()
    n = make(client=client)
    assert _arm(n).success
    _send(n, "high wave")
    assert client.calls == [HIGH_WAVE, RELEASE]
    assert status == ["armed", "started high wave", "done high wave"]
    assert inits == [("eth0", 10.0)]


def test_armed_param_arms_at_startup(make_node):
    make, status, inits = make_node
    make(client=_FakeClient(), armed=True)
    assert status == ["armed"]
    assert len(inits) == 1


def test_arming_twice_builds_the_client_once(make_node):
    make, _, inits = make_node
    n = make(client=_FakeClient())
    _arm(n)
    _arm(n)
    assert len(inits) == 1


def test_init_failure_keeps_node_disarmed_and_can_retry(make_node):
    make, status, inits = make_node
    n = make(factory_error=RuntimeError("sem DDS"))
    response = _arm(n)
    assert not response.success
    assert status[0].startswith("failed init") and "sem DDS" in status[0]
    _send(n, "high wave")
    assert status[-1] == "dry_run high wave"
    _arm(n)
    assert len(inits) == 2  # tentou de novo


def test_disarm_turns_commands_back_into_dry_run(make_node):
    make, status, _ = make_node
    client = _FakeClient()
    n = make(client=client)
    _arm(n)
    _arm(n, on=False)
    _send(n, "high wave")
    assert status == ["armed", "disarmed", "dry_run high wave"]
    assert client.calls == []


def test_failed_code_still_releases_arm(make_node):
    make, status, _ = make_node
    client = _FakeClient(codes={HIGH_WAVE: 3104})
    n = make(client=client)
    _arm(n)
    _send(n, "high wave")
    assert client.calls == [HIGH_WAVE, RELEASE]
    assert status[1:] == ["started high wave", "failed high wave code=3104"]


def test_sdk_exception_releases_and_does_not_leave_node_busy(make_node):
    make, status, _ = make_node
    client = _FakeClient(raises=RuntimeError("rpc caiu"))
    n = make(client=client)
    _arm(n)
    _send(n, "high wave")
    assert status[2].startswith("failed high wave") and "rpc caiu" in status[2]
    client.raises = None
    _send(n, "clap")
    assert status[-1] == "done clap"
    assert client.calls == [HIGH_WAVE, RELEASE, 17, RELEASE]


def test_second_command_while_busy_is_rejected_and_ctrl_c_releases(make_node):
    make, status, _ = make_node
    client = _FakeClient()
    client.gate = threading.Event()
    n = make(client=client)
    _arm(n)
    _send(n, "high wave", wait=False)
    _send(n, "clap", wait=False)
    n.release_if_busy()  # o que o main faz no Ctrl+C
    client.gate.set()
    n._worker.join(5)
    assert "rejected busy" in status
    assert client.calls.count(RELEASE) == 2  # o do Ctrl+C e o do fim do gesto
```

- [ ] **Step 2: Run test to verify it fails**

Run: `<docker-test>`
Expected: FAIL — `ModuleNotFoundError: No module named 'robot_reaction_ros.gesture_node'`

- [ ] **Step 3: Write minimal implementation**

`ros2_ws/src/robot_reaction_ros/robot_reaction_ros/gesture_node.py`:

```python
from __future__ import annotations

import threading
import time
from typing import Callable

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from std_srvs.srv import SetBool

from core.reaction_policy import GESTOS, RELEASE_ARM


def _sdk_client(network_interface: str, rpc_timeout_s: float) -> object:
    # Import tardio: desarmado, o nó roda sem o SDK da Unitree (notebook, Docker).
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    from unitree_sdk2py.g1.arm.g1_arm_action_client import G1ArmActionClient

    ChannelFactoryInitialize(0, network_interface)
    client = G1ArmActionClient()
    client.SetTimeout(rpc_timeout_s)
    client.Init()
    return client


class GestureNode(Node):
    """Único nó que fala com o firmware: executa gestos prontos (G1ArmActionClient).

    Nasce desarmado (dry-run). Nunca troca o modo do robô nem usa controle de baixo nível: o
    operador põe o robô em pé pelo controle. Spec: 2026-10-21-robot-reaction-design.md.
    """

    def __init__(self, client_factory: Callable[[str, float], object] = _sdk_client) -> None:
        super().__init__("gesture_node")
        self.declare_parameter("armed", False)
        self.declare_parameter("network_interface", "eth0")
        self.declare_parameter("hold_s", 2.0)
        self.declare_parameter("rpc_timeout_s", 10.0)
        self._network_interface = self.get_parameter("network_interface").value
        self._hold_s = float(self.get_parameter("hold_s").value)
        self._rpc_timeout_s = float(self.get_parameter("rpc_timeout_s").value)

        self._client_factory = client_factory
        self._client = None
        self._armed = False
        self._busy = threading.Lock()
        self._worker: threading.Thread | None = None

        self._status_pub = self.create_publisher(String, "/reaction/gesture_status", 10)
        self._subscription = self.create_subscription(String, "/reaction/gesture", self._on_gesture, 10)
        self._service = self.create_service(SetBool, "~/set_armed", self._on_set_armed)

        # `is True`: um "true"/"false" que chegasse como string seria verdadeiro e armaria o braço.
        if self.get_parameter("armed").value is True:
            self._set_armed(True)

    def _publish(self, text: str) -> None:
        self.get_logger().info(text)
        self._status_pub.publish(String(data=text))

    def _set_armed(self, armed: bool) -> tuple[bool, str]:
        if armed and self._client is None:
            try:
                self._client = self._client_factory(self._network_interface, self._rpc_timeout_s)
            except Exception as exc:  # sem SDK ou sem DDS: continua desarmado
                self._publish(f"failed init {exc!r}")
                return False, repr(exc)
        self._armed = armed
        self._publish("armed" if armed else "disarmed")
        return True, "armed" if armed else "disarmed"

    def _on_set_armed(self, request: SetBool.Request, response: SetBool.Response) -> SetBool.Response:
        response.success, response.message = self._set_armed(request.data)
        return response

    def _on_gesture(self, msg: String) -> None:
        gesto = msg.data
        if gesto not in GESTOS:
            self._publish(f"rejected unknown {gesto!r}")
            return
        if not self._armed:
            self._publish(f"dry_run {gesto}")
            return
        if not self._busy.acquire(blocking=False):
            self._publish("rejected busy")
            return
        # ExecuteAction bloqueia até o timeout: fora do callback, para não travar o executor do ROS.
        self._worker = threading.Thread(target=self._run, args=(gesto,), daemon=True)
        self._worker.start()

    def _run(self, gesto: str) -> None:
        try:
            self._publish(f"started {gesto}")
            ok = self._execute(gesto)
            if ok:
                time.sleep(self._hold_s)
            released = self._execute(RELEASE_ARM)  # mesmo se o gesto falhou
            if ok and released:
                self._publish(f"done {gesto}")
        finally:
            self._busy.release()

    def _execute(self, gesto: str) -> bool:
        try:
            code = self._client.ExecuteAction(GESTOS[gesto])
        except Exception as exc:  # um erro do SDK não pode deixar o nó preso em "ocupado"
            self._publish(f"failed {gesto} {exc!r}")
            return False
        if code != 0:
            self._publish(f"failed {gesto} code={code}")
            return False
        return True

    def release_if_busy(self) -> None:
        """Ctrl+C no meio de um gesto: tenta soltar o braço antes de sair."""
        if self._client is not None and self._busy.locked():
            self._execute(RELEASE_ARM)


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = None
    try:
        node = GestureNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        if node is not None:
            node.release_if_busy()
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():  # o Ctrl+C já pode ter desligado o contexto
            rclpy.shutdown()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `<docker-test>` e `PYTHONPATH=. .venv/bin/python -m pytest tests/test_future_annotations.py -v`
Expected: PASS (15 testes no Docker: 5 do reaction_node + 10 do gesture_node; os 2 do future_annotations)

- [ ] **Step 5: Commit**

```bash
git add ros2_ws/src/robot_reaction_ros/robot_reaction_ros/gesture_node.py ros2_ws/src/robot_reaction_ros/test/test_gesture_node.py
git commit -m "feat: add the gesture node, disarmed by default, with a status topic"
```

---

### Task 5: Launch de topo e `robo_tmux.sh`

**Files:**
- Create: `ros2_ws/src/robot_reaction_ros/launch/robo.launch.py`
- Delete: `ros2_ws/src/robot_reaction_ros/launch/.gitkeep`
- Modify: `scripts/robo_tmux.sh` (comentário do cabeçalho, linha do `rodar reconhecimento`, janela nova)

**Interfaces:**
- Consumes: executáveis `reaction_node` e `gesture_node` (Tasks 3–4); `face_recognition_ros/launch/face_recognition.launch.py` (inalterado — seus argumentos `camera`, `video_device`, `onnx_providers`, `model_root`… passam pela linha de comando).
- Produces: `ros2 launch robot_reaction_ros robo.launch.py [armed:=false] [reactions_file:=...] [args do reconhecimento]`.

- [ ] **Step 1: Escrever o launch**

`ros2_ws/src/robot_reaction_ros/launch/robo.launch.py`:

```python
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    # Câmera + reconhecimento: o launch de face_recognition_ros, sem mudanças. Os argumentos dele
    # (camera, video_device, onnx_providers, model_root...) chegam pela linha de comando.
    recognition = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(get_package_share_directory("face_recognition_ros"), "launch", "face_recognition.launch.py")
        )
    )
    armed_arg = DeclareLaunchArgument(
        "armed",
        default_value="false",
        description="true: o gesture_node mexe o braço de verdade. false: dry-run (só loga). "
        "Também dá para armar depois: ros2 service call /gesture_node/set_armed std_srvs/srv/SetBool '{data: true}'",
    )
    reactions_file_arg = DeclareLaunchArgument(
        "reactions_file",
        default_value="",
        description="Mapa pessoa -> gesto ('' = config/reactions.yaml do pacote)",
    )
    reaction_node = Node(
        package="robot_reaction_ros",
        executable="reaction_node",
        name="reaction_node",
        parameters=[{"reactions_file": LaunchConfiguration("reactions_file")}],
    )
    gesture_node = Node(
        package="robot_reaction_ros",
        executable="gesture_node",
        name="gesture_node",
        parameters=[{"armed": LaunchConfiguration("armed")}],
    )
    return LaunchDescription([armed_arg, reactions_file_arg, recognition, reaction_node, gesture_node])
```

Apagar `launch/.gitkeep`.

- [ ] **Step 2: Verificar no Docker que tudo sobe e que `armed` chega como bool**

```bash
docker run --rm -v "$(pwd)":/workspace -w /workspace face-recognition-ros2:local bash -c \
  "source /opt/ros/foxy/setup.bash && pip install --no-deps -e . >/dev/null && cd ros2_ws \
   && colcon build --symlink-install >/dev/null && source install/setup.bash \
   && (timeout 25 ros2 launch robot_reaction_ros robo.launch.py camera:=none model_root:=/opt/insightface &) \
   && sleep 15 && ros2 node list && ros2 param get /gesture_node armed \
   && ros2 topic pub --once /reaction/gesture std_msgs/msg/String '{data: high wave}' >/dev/null \
   && sleep 2; wait"
```

Expected: `ros2 node list` mostra `/reaction_node` e `/gesture_node` (o `/face_recognition_node` só fica de pé se houver banco em `data/identity_db_buffalo_l.*`; a falta dele aqui não importa); `Boolean value is: False`; no log do launch aparece `[gesture_node]: dry_run high wave`. Se `armed` vier como string (`String value is: false`), o `is True` do nó já o mantém desarmado — mas registre no relatório, porque `armed:=true` então não armaria.

- [ ] **Step 3: Ajustar o `robo_tmux.sh`**

Em `scripts/robo_tmux.sh`:

1. Cabeçalho — trocar as linhas das janelas por:

```bash
#   janela 0 "reconhecimento": um único launch com câmera + reconhecimento + reação + gesto
#            (gesto DESARMADO: só loga; armar com o serviço /gesture_node/set_armed)
#   janela 1 "deteccoes": watch_detections.py
#   janela 2 "gestos": eventos do gesture_node (/reaction/gesture_status)
#   janela "camera": só com realsense, que roda o driver da D435i à parte
```

2. Logo depois de `tmux new-window -t "$SESSAO" -n deteccoes "bash --norc"`, acrescentar:

```bash
tmux new-window -t "$SESSAO" -n gestos "bash --norc"
```

3. Trocar `rodar reconhecimento "ros2 launch face_recognition_ros face_recognition.launch.py $ARGS_CAMERA \` por:

```bash
rodar reconhecimento "ros2 launch robot_reaction_ros robo.launch.py $ARGS_CAMERA \
```

(a linha seguinte, `onnx_providers:=...`, fica igual).

4. Depois de `rodar deteccoes "python3 $REPO/scripts/watch_detections.py"`, acrescentar:

```bash
rodar gestos "ros2 topic echo /reaction/gesture_status"
```

5. Na mensagem final, trocar `(Ctrl+b e 0/1 troca de janela)` por `(Ctrl+b e 0/1/2 troca de janela)`.

Verificar sintaxe: `bash -n scripts/robo_tmux.sh` (sem saída = ok).

- [ ] **Step 4: Rodar os testes de novo**

Run: `<docker-test>`
Expected: PASS (15 testes)

- [ ] **Step 5: Commit**

```bash
git add ros2_ws/src/robot_reaction_ros/launch scripts/robo_tmux.sh
git commit -m "feat: one launch for recognition and reaction, used by robo_tmux.sh"
```

---

### Task 6: Documentação

**Files:**
- Modify: `docs/guides/jetson-deployment.md` (seção "### Um comando (recomendado)" e "## 8. Falar com o robô (Fase 2)")
- Modify: `README.md` (seção "## Estado atual" e "### No robô")

- [ ] **Step 1: Guia do robô**

Em `docs/guides/jetson-deployment.md`, na lista de janelas de "### Um comando (recomendado)", trocar a da janela 0 e acrescentar a 2:

```markdown
- **janela 0 `reconhecimento`** — um único `ros2 launch robot_reaction_ros robo.launch.py` que
  sobe a webcam (`v4l2_camera`, 640x480, achada pelo caminho estável
  `/dev/v4l/by-id/...-video-index0`), o nó de reconhecimento **e** os nós de reação e de gesto
  (gesto **desarmado**: só loga — ver passo 8);
- **janela 1 `deteccoes`** — `watch_detections.py`, que imprime `nome: nota` por rosto (ou
  `(nenhum rosto)`) a cada frame;
- **janela 2 `gestos`** — eventos do nó de gesto (`dry_run high wave`, `started`, `done`, `failed …`);
- **janela `camera`** — só no modo `realsense`.
```

Substituir a seção "## 8. Falar com o robô (Fase 2)" inteira por:

````markdown
## 8. Reação a uma pessoa (Fase 2)

Spec: [`2026-10-21-robot-reaction-design.md`](../superpowers/specs/2026-10-21-robot-reaction-design.md).
Quem aparece em `robot_reaction_ros/config/reactions.yaml` por 5 frames seguidos faz o robô
executar o gesto do firmware associado (cooldown de 60 s por pessoa e 10 s entre reações).

O ambiente obrigatório (prompt do fishros) já põe o CycloneDDS na `eth0`, a interface da rede
do robô — a mesma que o `gesture_node` usa para o SDK da Unitree.

**O nó de gesto nasce desarmado:** ele só publica `dry_run <gesto>` na janela `gestos`. Para mexer
o braço de verdade — robô em pé pelo controle, alguém perto, autor do `~/hhhh` avisado e **sem
apertar os combos do joystick dele** enquanto o nosso estiver armado:

```bash
ros2 service call /gesture_node/set_armed std_srvs/srv/SetBool "{data: true}"    # arma
ros2 service call /gesture_node/set_armed std_srvs/srv/SetBool "{data: false}"   # desarma
ros2 topic pub --once /reaction/gesture std_msgs/msg/String "data: high wave"   # gesto à mão
```

Desarmar não interrompe um gesto em andamento. `failed <gesto> code=<n>` na janela `gestos` é o
firmware recusando (por exemplo, robô fora do modo em pé). Para mudar quem dispara o quê, edite o
`reactions.yaml` (gestos válidos: `GESTOS` em `core/reaction_policy.py`), rode
`python3 -m colcon build --symlink-install` e reinicie a janela 0.
````

- [ ] **Step 2: README**

Em `README.md`, no parágrafo de "## Estado atual", trocar a frase `Próximo passo (Fase 2): disparar a interação (aproximação + continência) a partir do reconhecimento.` por:

```markdown
Fase 2 em andamento: o robô reage com um gesto do firmware quando reconhece uma pessoa do mapa
(`robot_reaction_ros`, desarmado por padrão); áudio/TTS fica para depois.
```

e acrescentar à lista de specs:

```markdown
- [`docs/superpowers/specs/2026-10-21-robot-reaction-design.md`](docs/superpowers/specs/2026-10-21-robot-reaction-design.md) — reação a uma pessoa (gestos)
```

Em "### No robô", trocar o comentário do comando por `# webcam + reconhecimento + reação (gesto desarmado)`.

- [ ] **Step 3: Conferir links**

Run: `grep -n "robot-reaction-design" README.md docs/guides/jetson-deployment.md && ls docs/superpowers/specs/2026-10-21-robot-reaction-design.md`
Expected: as duas referências e o arquivo existindo.

- [ ] **Step 4: Commit**

```bash
git add docs/guides/jetson-deployment.md README.md
git commit -m "docs: document the reaction launch, arming and the gestures window"
```

---

### Task 7: Validação no robô (o usuário roda; o agente só orienta e registra)

**Files:**
- Modify: `docs/superpowers/specs/2026-10-21-robot-reaction-design.md` (nova seção "## Implantação no robô" no fim, com o que o usuário relatar)

Pré-requisito: o usuário fez `git push` e, no robô, `cd ~/ipe-2-code && git pull && cd ros2_ws && python3 -m colcon build --symlink-install` (com o ambiente da opção 1 do fishros). O agente não roda comandos que modificam o robô.

- [ ] **Step 1: Degrau 1 — cadeia inteira desarmada**

Usuário: `~/ipe-2-code/scripts/robo_tmux.sh && tmux attach -t face`; `gil` na frente da webcam.
Esperado na janela 2 (`gestos`): **um** `dry_run high wave`; outro só depois de 60 s com ele ainda lá. Ninguém mexe no braço.

- [ ] **Step 2: Degrau 2 — gesto isolado, armado**

Robô em pé pelo controle, operador perto, autor do `~/hhhh` avisado. Num terminal com o ambiente: `ros2 run robot_reaction_ros gesture_node --ros-args -p armed:=true` e, noutro, `ros2 topic pub --once /reaction/gesture std_msgs/msg/String "data: high wave"`.
Registrar: (a) `armed` sem `failed init` — senão é o risco 1 da spec (duas pilhas DDS) e o plano B (SDK num processo filho) vira uma nova task; (b) se o gesto saiu e o código de retorno; (c) quanto tempo entre `started` e `done` comparado à duração real do gesto (risco 2: o `ExecuteAction` retorna no começo ou no fim? ajustar `hold_s`); (d) em que modo o robô estava.

- [ ] **Step 3: Degrau 3 — cadeia inteira armada**

`robo_tmux.sh`, armar pelo serviço, `gil` aparece → o robô acena **uma vez**; `ze_batista` (cadastrado, fora do mapa) e um desconhecido não provocam nada.

- [ ] **Step 4: Registrar e commitar**

Acrescentar ao fim da spec uma seção `## Implantação no robô` com data e o resultado de cada degrau (incluindo códigos de erro e o `hold_s` final, se mudou). Commit:

```bash
git add docs/superpowers/specs/2026-10-21-robot-reaction-design.md
git commit -m "docs: record the reaction rollout on the robot"
```
