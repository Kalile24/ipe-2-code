# Migração para nó ROS2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Embrulhar o pipeline de reconhecimento facial existente (`core/face_engine.py`, `core/identity_store.py`) num nó ROS2 (`face_recognition_node`) testável localmente via webcam, sem exigir acesso ao robô Unitree G1.

**Architecture:** `core/` continua puro (sem `rclpy`/`vision_msgs`/`cv_bridge`), instalado como pacote editável (`pip install -e .`) para que um pacote ROS2 novo (`face_recognition_ros`, `ament_python`) o importe. O nó assina `sensor_msgs/Image`, roda o mesmo pipeline com o mesmo throttling do protótipo, e publica `vision_msgs/Detection2DArray`. Um `launch` sobe `v4l2_camera_node` (webcam local) + o nó, remapeando o tópico de imagem para o nome padrão que o robô real (`realsense2_camera`) também usa — só o nó de câmera troca na portagem futura. Tudo roda dentro de um container Docker (`osrf/ros:humble-desktop`), pois o ambiente de desenvolvimento não tem ROS2 nativo.

**Tech Stack:** ROS2 Humble (`rclpy`, `sensor_msgs`, `vision_msgs`, `cv_bridge`, `v4l2_camera`), Docker, Python (`core/` existente: numpy, opencv-python, onnxruntime, insightface), pytest.

**Spec:** `docs/superpowers/specs/2026-09-12-ros2-node-migration-design.md`

## Global Constraints

- Imagem base do container: `osrf/ros:humble-desktop` (Ubuntu 22.04 + ROS2 Humble) — exigência do spec, não trocar por outra distro/versão.
- `core/` nunca importa `rclpy`, `vision_msgs` ou `cv_bridge` — desacoplamento obrigatório (mesmo princípio já usado com `apps/`).
- `pip install -e .` deve ser **editável** (nunca cópia) — `Path(__file__)` em `core/config.py` precisa continuar apontando para o repo real.
- Tópico de imagem default do nó: `/camera/color/image_raw` (nome padrão do `realsense2_camera`, para casar com o robô real sem overrides).
- Tópico de detecções default: `/face_recognition/detections`.
- QoS de fila de profundidade **1** em subscription e publisher (evita acumular frames atrasados, mesmo motivo do `CAP_PROP_BUFFERSIZE=1` do protótipo).
- Reaproveita `RECOGNITION_INTERVAL_FRAMES` de `core/config.py` para throttling (CPU sem GPU, mesmo gargalo do protótipo).
- Nenhum rosto detectado → publica `Detection2DArray` vazio (sinal de "vivo"), não é erro.
- Falha de `cv_bridge` ao converter frame → loga aviso, descarta o frame, segue (não derruba o nó).

---

## File Structure

```
ipe-2-code/
├── pyproject.toml                          # novo
├── docker/
│   └── ros2.Dockerfile                     # novo
├── core/config.py                          # modificado: paths ancorados ao repo root
└── ros2_ws/
    └── src/
        └── face_recognition_ros/
            ├── package.xml                         # novo
            ├── setup.py                            # novo
            ├── setup.cfg                           # novo
            ├── resource/face_recognition_ros        # novo (marker ament)
            ├── face_recognition_ros/
            │   ├── __init__.py                     # novo
            │   ├── message_builder.py              # novo — função pura
            │   └── face_recognition_node.py        # novo — o nó
            ├── launch/
            │   └── face_recognition.launch.py      # novo
            └── test/
                └── test_message_builder.py         # novo
```

**Nota de ambiente:** este repositório roda em WSL sem Docker/ROS2 instalado no host do agente. As tarefas 1 e 3 (Python puro) rodam e testam normalmente com `pytest`. As tarefas 2, 4 e 5 (Docker/ROS2) só podem ser **validadas manualmente pelo usuário**, que tem Docker configurado na sua distro — cada uma dessas tarefas termina com um passo manual explícito em vez de um `pytest` automatizado.

---

### Task 1: Tornar `core/` instalável e ancorar paths ao repo root

**Files:**
- Create: `pyproject.toml`
- Modify: `core/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `core.config.KNOWN_FACES_DIR: str` e `core.config.DB_PATH: str`, agora caminhos absolutos (antes eram relativos ao cwd). Todas as demais constantes (`CAMERA_INDEX`, `SIMILARITY_THRESHOLD`, `DET_SIZE`, `RECOGNITION_INTERVAL_FRAMES`) inalteradas.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/test_config.py
from pathlib import Path

from core import config


def test_known_faces_dir_is_absolute_and_under_repo_root():
    repo_root = Path(__file__).resolve().parent.parent
    assert Path(config.KNOWN_FACES_DIR).is_absolute()
    assert Path(config.KNOWN_FACES_DIR) == repo_root / "data" / "known_faces"


def test_db_path_is_absolute_and_under_repo_root():
    repo_root = Path(__file__).resolve().parent.parent
    assert Path(config.DB_PATH).is_absolute()
    assert Path(config.DB_PATH) == repo_root / "data" / "identity_db"
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL (`AssertionError`, paths ainda relativos: `"data/known_faces"` != caminho absoluto).

- [ ] **Step 3: Implementar**

```python
# core/config.py
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

CAMERA_INDEX = 0
SIMILARITY_THRESHOLD = 0.45
DET_SIZE = (640, 640)
KNOWN_FACES_DIR = str(_REPO_ROOT / "data" / "known_faces")
DB_PATH = str(_REPO_ROOT / "data" / "identity_db")
# Em CPU, o reconhecimento (ArcFace) roda bem mais devagar que a detecção
# sozinha; rodar o reconhecimento só a cada N frames mantém o vídeo fluido.
RECOGNITION_INTERVAL_FRAMES = 10
```

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "face-recognition-core"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "numpy==2.5.3",
    "opencv-python==5.0.0.93",
    "onnxruntime==1.30.0",
    "insightface==2.0",
]

[tool.setuptools]
packages = ["core"]
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: PASS (2 testes).

- [ ] **Step 5: Rodar a suíte inteira existente para checar regressão**

Run: `.venv/bin/python -m pytest -v`
Expected: PASS (todos os testes existentes de `core/` continuam passando — `enroll.py`/`webcam_demo.py` usam `KNOWN_FACES_DIR`/`DB_PATH` só como argumento string, então o valor absoluto não quebra nada).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml core/config.py tests/test_config.py
git commit -m "feat: anchor core config paths to repo root, add pyproject.toml"
```

---

### Task 2: `docker/ros2.Dockerfile` + verificação empírica de imports

**Files:**
- Create: `docker/ros2.Dockerfile`

**Interfaces:**
- Produces: uma imagem Docker local (`face-recognition-ros2`, tag `local`) com ROS2 Humble + `rclpy`, `cv_bridge`, `vision_msgs`, `v4l2_camera` (via `apt`) e `numpy`/`opencv-python`/`onnxruntime`/`insightface`/`pytest` (via `pip`), mais `core/` instalado editável a partir do volume montado em `/workspace`.
- Consumes: `requirements.txt` (raiz do repo, já existente) e `pyproject.toml` (Task 1).

- [ ] **Step 1: Escrever o Dockerfile**

```dockerfile
# docker/ros2.Dockerfile
FROM osrf/ros:humble-desktop

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-pip \
        ros-humble-cv-bridge \
        ros-humble-vision-msgs \
        ros-humble-v4l2-camera \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /workspace

RUN echo "source /opt/ros/humble/setup.bash" >> /root/.bashrc
```

- [ ] **Step 2: Construir a imagem (manual, usuário — precisa de Docker)**

Run (no host com Docker, na raiz do repo):
```bash
docker build -f docker/ros2.Dockerfile -t face-recognition-ros2:local .
```
Expected: build termina sem erro (`Successfully tagged face-recognition-ros2:local`).

- [ ] **Step 3: Instalar `core/` editável dentro do container e verificar o import conjunto (manual, usuário)**

Run:
```bash
docker run --rm -v "$(pwd)":/workspace -w /workspace face-recognition-ros2:local \
  bash -lc "source /opt/ros/humble/setup.bash && pip install -e . && python3 -c 'import cv2, rclpy, cv_bridge, vision_msgs; print(\"OK\", cv2.__version__)'"
```
Expected: imprime `OK <versão>` sem `ImportError`/`ImportWarning` de símbolo do OpenCV.

**Se houver conflito de binário** entre o `opencv-python` do `pip` e o OpenCV que o `cv_bridge` (`apt`) espera (risco identificado no spec): remover `opencv-python` de `requirements.txt`/`pyproject.toml` dentro deste Dockerfile (ele já vem transitivamente com `ros-humble-cv-bridge`/imagem `-desktop`) e repetir o Step 3. Documentar a decisão tomada como comentário no Dockerfile antes de seguir para a Task 3.

- [ ] **Step 4: Commit**

```bash
git add docker/ros2.Dockerfile
git commit -m "feat: add ROS2 Humble Dockerfile for local face recognition node testing"
```

---

### Task 3: Esqueleto do pacote ROS2 `face_recognition_ros`

**Files:**
- Create: `ros2_ws/src/face_recognition_ros/package.xml`
- Create: `ros2_ws/src/face_recognition_ros/setup.py`
- Create: `ros2_ws/src/face_recognition_ros/setup.cfg`
- Create: `ros2_ws/src/face_recognition_ros/resource/face_recognition_ros`
- Create: `ros2_ws/src/face_recognition_ros/face_recognition_ros/__init__.py`

**Interfaces:**
- Produces: pacote `ament_python` instalável via `colcon build`, com entry point de nó `face_recognition_node = face_recognition_ros.face_recognition_node:main` (implementado na Task 5) e acesso ao `launch/` (Task 6).

- [ ] **Step 1: `package.xml`**

```xml
<?xml version="1.0"?>
<package format="3">
  <name>face_recognition_ros</name>
  <version>0.1.0</version>
  <description>Nó ROS2 de reconhecimento facial para o Unitree G1</description>
  <maintainer email="marcoskmvasconcellos@gmail.com">Marcos Kalile</maintainer>
  <license>Apache-2.0</license>

  <buildtool_depend>ament_python</buildtool_depend>

  <exec_depend>rclpy</exec_depend>
  <exec_depend>sensor_msgs</exec_depend>
  <exec_depend>vision_msgs</exec_depend>
  <exec_depend>cv_bridge</exec_depend>
  <exec_depend>v4l2_camera</exec_depend>

  <test_depend>ament_copyright</test_depend>
  <test_depend>ament_flake8</test_depend>
  <test_depend>ament_pep257</test_depend>
  <test_depend>python3-pytest</test_depend>

  <export>
    <build_type>ament_python</build_type>
  </export>
</package>
```

- [ ] **Step 2: `setup.py`**

```python
from setuptools import find_packages, setup

package_name = "face_recognition_ros"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", ["launch/face_recognition.launch.py"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Marcos Kalile",
    maintainer_email="marcoskmvasconcellos@gmail.com",
    description="Nó ROS2 de reconhecimento facial para o Unitree G1",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "face_recognition_node = face_recognition_ros.face_recognition_node:main",
        ],
    },
)
```

- [ ] **Step 3: `setup.cfg`**

```ini
[develop]
script_dir=$base/lib/face_recognition_ros
[install]
install_scripts=$base/lib/face_recognition_ros
```

- [ ] **Step 4: marker de recurso e `__init__.py`**

```bash
mkdir -p ros2_ws/src/face_recognition_ros/resource
touch ros2_ws/src/face_recognition_ros/resource/face_recognition_ros
touch ros2_ws/src/face_recognition_ros/face_recognition_ros/__init__.py
```

(`launch/face_recognition.launch.py` referenciado no `data_files` do Step 2 é criado na Task 6 — o `setup.py` já aponta para o caminho final para não precisar editar de novo.)

- [ ] **Step 5: Commit**

```bash
git add ros2_ws/src/face_recognition_ros/package.xml \
        ros2_ws/src/face_recognition_ros/setup.py \
        ros2_ws/src/face_recognition_ros/setup.cfg \
        ros2_ws/src/face_recognition_ros/resource/face_recognition_ros \
        ros2_ws/src/face_recognition_ros/face_recognition_ros/__init__.py
git commit -m "feat: scaffold face_recognition_ros ament_python package"
```

---

### Task 4: `message_builder.py` — função pura, testável sem `rclpy`

**Files:**
- Create: `ros2_ws/src/face_recognition_ros/face_recognition_ros/message_builder.py`
- Test: `ros2_ws/src/face_recognition_ros/test/test_message_builder.py`

**Interfaces:**
- Consumes: nada de `core/` ou de outras tasks.
- Produces: `build_detection(bbox: tuple[int, int, int, int], name: str | None, score: float) -> vision_msgs.msg.Detection2D`, usado pela Task 5 (`face_recognition_node.py`).

**Nota de ambiente:** `vision_msgs` só existe dentro do container ROS2 (Task 2). Este teste roda com `pytest` **dentro do container** (ou em qualquer ambiente com `vision_msgs` instalado) — não com o `.venv` do protótipo standalone, que não tem `rclpy`/`vision_msgs`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# ros2_ws/src/face_recognition_ros/test/test_message_builder.py
from face_recognition_ros.message_builder import build_detection


def test_build_detection_known_person_sets_class_id_and_score():
    detection = build_detection(bbox=(10, 20, 110, 220), name="alice", score=0.87)

    assert detection.results[0].hypothesis.class_id == "alice"
    assert detection.results[0].hypothesis.score == 0.87


def test_build_detection_unknown_person_uses_desconhecido_label():
    detection = build_detection(bbox=(0, 0, 50, 50), name=None, score=0.2)

    assert detection.results[0].hypothesis.class_id == "desconhecido"


def test_build_detection_bbox_center_and_size():
    detection = build_detection(bbox=(10, 20, 110, 220), name="alice", score=0.87)

    assert detection.bbox.center.position.x == 60.0
    assert detection.bbox.center.position.y == 120.0
    assert detection.bbox.size_x == 100.0
    assert detection.bbox.size_y == 200.0
```

- [ ] **Step 2: Rodar e confirmar que falha (dentro do container, ver Task 2 Step 2)**

Run:
```bash
docker run --rm -v "$(pwd)":/workspace -w /workspace/ros2_ws/src/face_recognition_ros face-recognition-ros2:local \
  bash -lc "source /opt/ros/humble/setup.bash && python3 -m pytest test/test_message_builder.py -v"
```
Expected: FAIL (`ModuleNotFoundError: No module named 'face_recognition_ros.message_builder'`).

- [ ] **Step 3: Implementar**

```python
# ros2_ws/src/face_recognition_ros/face_recognition_ros/message_builder.py
from vision_msgs.msg import Detection2D, ObjectHypothesisWithPose


def build_detection(
    bbox: tuple[int, int, int, int], name: str | None, score: float
) -> Detection2D:
    x1, y1, x2, y2 = bbox

    detection = Detection2D()
    detection.bbox.center.position.x = float((x1 + x2) / 2)
    detection.bbox.center.position.y = float((y1 + y2) / 2)
    detection.bbox.size_x = float(x2 - x1)
    detection.bbox.size_y = float(y2 - y1)

    hypothesis = ObjectHypothesisWithPose()
    hypothesis.hypothesis.class_id = name if name else "desconhecido"
    hypothesis.hypothesis.score = float(score)
    detection.results.append(hypothesis)

    return detection
```

- [ ] **Step 4: Rodar e confirmar que passa (mesmo comando do Step 2)**

Expected: PASS (3 testes).

- [ ] **Step 5: Commit**

```bash
git add ros2_ws/src/face_recognition_ros/face_recognition_ros/message_builder.py \
        ros2_ws/src/face_recognition_ros/test/test_message_builder.py
git commit -m "feat: add build_detection message builder with tests"
```

---

### Task 5: `face_recognition_node.py`

**Files:**
- Create: `ros2_ws/src/face_recognition_ros/face_recognition_ros/face_recognition_node.py`

**Interfaces:**
- Consumes: `core.face_engine.FaceEngine(det_size)` / `.extract_faces(frame) -> list[FaceResult]` (Task anterior ao plano, já existe); `core.identity_store.IdentityStore(db_path)` / `.load()` / `.match(embedding, threshold) -> (name | None, score)` (já existe); `core.config.{DB_PATH, SIMILARITY_THRESHOLD, DET_SIZE, RECOGNITION_INTERVAL_FRAMES}` (Task 1); `message_builder.build_detection(bbox, name, score) -> Detection2D` (Task 4).
- Produces: entry point `main()` chamado por `console_scripts` (Task 3) e por `launch/face_recognition.launch.py` (Task 6).

- [ ] **Step 1: Implementar o nó**

```python
# ros2_ws/src/face_recognition_ros/face_recognition_ros/face_recognition_node.py
import rclpy
from cv_bridge import CvBridge, CvBridgeError
from rclpy.node import Node
from rclpy.qos import QoSProfile
from sensor_msgs.msg import Image
from vision_msgs.msg import Detection2DArray

from core.config import DB_PATH, DET_SIZE, RECOGNITION_INTERVAL_FRAMES, SIMILARITY_THRESHOLD
from core.face_engine import FaceEngine
from core.identity_store import IdentityStore

from face_recognition_ros.message_builder import build_detection


class FaceRecognitionNode(Node):
    def __init__(self) -> None:
        super().__init__("face_recognition_node")

        self.declare_parameter("image_topic", "/camera/color/image_raw")
        self.declare_parameter("detections_topic", "/face_recognition/detections")
        self.declare_parameter("similarity_threshold", SIMILARITY_THRESHOLD)
        self.declare_parameter("db_path", DB_PATH)

        image_topic = self.get_parameter("image_topic").value
        detections_topic = self.get_parameter("detections_topic").value
        self._threshold = self.get_parameter("similarity_threshold").value
        db_path = self.get_parameter("db_path").value

        self._bridge = CvBridge()
        self._engine = FaceEngine(det_size=DET_SIZE)
        self._store = IdentityStore(db_path)
        self._store.load()
        if not self._store.embeddings:
            self.get_logger().warn(
                f"Nenhuma identidade cadastrada em {db_path}; "
                "todos os rostos serão marcados como desconhecido."
            )

        self._frame_count = 0
        self._last_detections: list[tuple[tuple[int, int, int, int], str | None, float]] = []

        qos = QoSProfile(depth=1)
        self._subscription = self.create_subscription(Image, image_topic, self._on_image, qos)
        self._publisher = self.create_publisher(Detection2DArray, detections_topic, qos)

    def _on_image(self, msg: Image) -> None:
        try:
            frame = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except CvBridgeError as exc:
            self.get_logger().warn(f"Falha ao converter frame: {exc}")
            return

        if self._frame_count % RECOGNITION_INTERVAL_FRAMES == 0:
            self._last_detections = []
            for face in self._engine.extract_faces(frame):
                name, score = self._store.match(face.embedding, self._threshold)
                self._last_detections.append((face.bbox, name, score))
        self._frame_count += 1

        detections_msg = Detection2DArray()
        detections_msg.header = msg.header
        detections_msg.detections = [
            build_detection(bbox, name, score) for bbox, name, score in self._last_detections
        ]
        self._publisher.publish(detections_msg)


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = FaceRecognitionNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verificar sintaticamente sem rodar ROS2 (rápido, no host, sem precisar do container)**

Run: `.venv/bin/python -m py_compile ros2_ws/src/face_recognition_ros/face_recognition_ros/face_recognition_node.py`
Expected: sem output, exit code 0 (arquivo compila; ele não roda de verdade fora do container porque `rclpy`/`vision_msgs`/`cv_bridge` não existem no `.venv`).

- [ ] **Step 3: Commit**

```bash
git add ros2_ws/src/face_recognition_ros/face_recognition_ros/face_recognition_node.py
git commit -m "feat: add face_recognition_node subscribing to Image, publishing Detection2DArray"
```

---

### Task 6: `launch/face_recognition.launch.py` + validação manual ponta a ponta

**Files:**
- Create: `ros2_ws/src/face_recognition_ros/launch/face_recognition.launch.py`

**Interfaces:**
- Consumes: `face_recognition_node` (entry point da Task 3/5), pacote `v4l2_camera` (`apt`, Task 2).
- Produces: comando `ros2 launch face_recognition_ros face_recognition.launch.py`.

- [ ] **Step 1: Implementar o launch**

```python
# ros2_ws/src/face_recognition_ros/launch/face_recognition.launch.py
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    v4l2_camera_node = Node(
        package="v4l2_camera",
        executable="v4l2_camera_node",
        name="v4l2_camera_node",
        remappings=[("/image_raw", "/camera/color/image_raw")],
    )

    face_recognition_node = Node(
        package="face_recognition_ros",
        executable="face_recognition_node",
        name="face_recognition_node",
    )

    return LaunchDescription([v4l2_camera_node, face_recognition_node])
```

- [ ] **Step 2: Build do workspace ROS2 (manual, usuário, dentro do container)**

Run:
```bash
docker run --rm -it -v "$(pwd)":/workspace -w /workspace --device=/dev/video0 --group-add video \
  face-recognition-ros2:local bash -lc \
  "source /opt/ros/humble/setup.bash && pip install -e . && cd ros2_ws && colcon build --symlink-install"
```
Expected: `colcon build` termina com `Summary: 1 package finished`.

- [ ] **Step 3: Rodar o teste do `message_builder` via `colcon test` (manual, usuário)**

Run (mesmo container, após o build):
```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
cd ros2_ws && colcon test --packages-select face_recognition_ros && colcon test-result --verbose
```
Expected: `test_message_builder.py` — 3 testes passando, 0 falhas.

- [ ] **Step 4: Validação manual ponta a ponta com a webcam (manual, usuário)**

Terminal 1 (dentro do container):
```bash
source /opt/ros/humble/setup.bash && source ros2_ws/install/setup.bash && \
ros2 launch face_recognition_ros face_recognition.launch.py
```

Terminal 2 (outro shell no mesmo container, `docker exec`):
```bash
source /opt/ros/humble/setup.bash && ros2 topic echo /face_recognition/detections
```

Expected: mensagens `Detection2DArray` chegando continuamente; com pelo menos uma pessoa cadastrada (`data/known_faces/`) na frente da câmera, `results[0].hypothesis.class_id` mostra o nome (ou `"desconhecido"`) e `score` a confiança.

- [ ] **Step 5: Commit**

```bash
git add ros2_ws/src/face_recognition_ros/launch/face_recognition.launch.py
git commit -m "feat: add launch file wiring v4l2_camera to face_recognition_node"
```

---

## Self-Review

**1. Cobertura do spec:**
- Ambiente Docker (`osrf/ros:humble-desktop`, `docker/ros2.Dockerfile`, deps `apt`/`pip`, volume, webcam via `--device`) → Task 2, Task 6 Step 2/4.
- Risco `cv_bridge`/`opencv-python` a verificar empiricamente → Task 2 Step 3 (com fallback documentado).
- `pyproject.toml` + paths ancorados ao repo root → Task 1.
- Estrutura de pacote ROS2 (`package.xml`, `setup.py`, layout) → Task 3.
- Interface do nó (tópicos default, QoS depth 1, throttling, params) → Task 5.
- `message_builder.py` puro e testável → Task 4.
- Launch com remap e troca só do nó de câmera na portagem → Task 6.
- Tratamento de erros (`cv_bridge` falha, DB vazio, zero rostos) → Task 5.
- Validação manual via `ros2 topic echo` → Task 6 Step 4.

**2. Placeholders:** nenhum "TBD"/"implementar depois" — todo step tem código ou comando completo.

**3. Consistência de tipos:** `build_detection(bbox, name, score) -> Detection2D` (Task 4) usado identicamente em `face_recognition_node.py` (Task 5); `IdentityStore.match` e `FaceEngine.extract_faces` usados com as mesmas assinaturas já existentes em `core/`; `KNOWN_FACES_DIR`/`DB_PATH`/`SIMILARITY_THRESHOLD`/`DET_SIZE`/`RECOGNITION_INTERVAL_FRAMES` usados com os mesmos nomes em todas as tasks.
