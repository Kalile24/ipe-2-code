# Reconhecimento Facial — Unitree G1

Projeto institucional do IME (Instituto Militar de Engenharia), disciplina
**IPE II — Introdução a Projetos de Engenharia**.

Vai colaborar? Comece pelo [`CONTRIBUTING.md`](CONTRIBUTING.md) (ferramentas de IA, memória
compartilhada, fluxo de specs e convenções).

## Objetivo

Reconhecer pessoas em vídeo ao vivo a partir de poucas fotos de referência,
como etapa inicial de um sistema de interação do robô humanoide **Unitree
G1**: o robô deve identificar uma pessoa conhecida e iniciar uma interação
apropriada (ex: reconhecer o general, se aproximar e prestar continência).

## Estado atual

**Fase 1 (reconhecimento) implantada no robô (2026-10-09):** nó ROS2
(`face_recognition_node`) rodando no Jetson Orin NX do Unitree G1 EDU com GPU (TensorRT,
~42 ms por frame), a partir de uma webcam USB presa no alto da cabeça do robô — a D435i de
fábrica olha para o chão. Também roda localmente, em Docker com o mesmo ROS2 Foxy / Ubuntu
20.04 / Python 3.8 do robô, e como protótipo standalone. Próximo passo (Fase 2): disparar a
interação (aproximação + continência) a partir do reconhecimento. Specs completas:

- [`docs/superpowers/specs/2026-09-10-facial-recognition-design.md`](docs/superpowers/specs/2026-09-10-facial-recognition-design.md) — protótipo standalone
- [`docs/superpowers/specs/2026-09-12-ros2-node-migration-design.md`](docs/superpowers/specs/2026-09-12-ros2-node-migration-design.md) — migração para nó ROS2
- [`docs/superpowers/specs/2026-09-18-jetson-gpu-migration-design.md`](docs/superpowers/specs/2026-09-18-jetson-gpu-migration-design.md) — portagem para o robô (Foxy + GPU)

## Sobre o robô — Unitree G1 EDU

- **Compute:** NVIDIA Jetson Orin NX (100–157 TOPS conforme variante) + CPU 8 núcleos.
- **Câmera:** Intel RealSense D435i (RGB + profundidade + IMU), fixa e inclinada 47,6° para
  baixo. Para rostos de pessoas em pé, este projeto usa uma webcam USB extra na cabeça.
- **LiDAR:** Livox MID-360.
- **Computador de desenvolvimento (PC2):** JetPack 5.1.1 (Ubuntu 20.04, Python 3.8). Exemplos ROS2 oficiais em Foxy.

Referências:
- [Página oficial do produto (unitree.com/g1)](https://www.unitree.com/g1/)
- [SDK oficial ROS2 (github.com/unitreerobotics/unitree_ros2)](https://github.com/unitreerobotics/unitree_ros2)

## Stack

Python + [InsightFace](https://github.com/deepinsight/insightface)
(detecção RetinaFace + embeddings ArcFace) via ONNX Runtime — TensorRT na Jetson do robô,
CPU no desenvolvimento.

## Como rodar

### Protótipo standalone (webcam direta, sem ROS2)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Cadastrar pessoas conhecidas (coloque fotos em `data/known_faces/<nome>/`,
não versionadas):

```bash
.venv/bin/python -m apps.enroll
```

Rodar o reconhecimento ao vivo pela webcam (ou por um vídeo gravado):

```bash
.venv/bin/python -m apps.webcam_demo
.venv/bin/python -m apps.webcam_demo --source caminho/para/video.mp4
```

`--model` escolhe o pacote do InsightFace (`buffalo_l` default, ou `buffalo_s`/`buffalo_sc` — mais leves, trocam acurácia por latência; cada um usa seu próprio banco de identidades). Aceito em `enroll` e `webcam_demo`; detalhes em [`docs/guides/ros2-docker.md`](docs/guides/ros2-docker.md#6-escolha-de-modelo-latência-vs-acurácia).

### Nó ROS2 (Docker)

Requer Docker (usuário no grupo `docker`) e uma webcam em `/dev/video0`.

```bash
docker build -f docker/ros2.Dockerfile -t face-recognition-ros2:local .

docker run --rm -it --device=/dev/video0 --group-add video \
  -v "$(pwd)":/workspace -w /workspace face-recognition-ros2:local bash

# dentro do container:
pip install --no-deps -e .   # dependências já estão na imagem
cd ros2_ws
colcon build --symlink-install
source install/setup.bash
ros2 launch face_recognition_ros face_recognition.launch.py
```

Em outro terminal, pra ver as detecções chegando:

```bash
docker exec -it <container_id> bash -lc \
  "source /opt/ros/foxy/setup.bash && ros2 topic echo /face_recognition/detections"
```

Guia completo (build, testes, troubleshooting, cadastro de pessoas):
[`docs/guides/ros2-docker.md`](docs/guides/ros2-docker.md).

### No robô (Jetson Orin NX do G1)

```bash
~/ipe-2-code/scripts/robo_tmux.sh && tmux attach -t face    # webcam + reconhecimento + detecções
```

Instalação nativa (ROS2 Foxy + venv Python 3.8 + `onnxruntime-gpu`), convivência com os outros
projetos do robô e problemas comuns: [`docs/guides/jetson-deployment.md`](docs/guides/jetson-deployment.md).
