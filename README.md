# Reconhecimento Facial — Unitree G1

Projeto institucional do IME (Instituto Militar de Engenharia), disciplina
**IPE II — Introdução a Projetos de Engenharia**.

## Objetivo

Reconhecer pessoas em vídeo ao vivo a partir de poucas fotos de referência,
como etapa inicial de um sistema de interação do robô humanoide **Unitree
G1**: o robô deve identificar uma pessoa conhecida e iniciar uma interação
apropriada (ex: reconhecer o general, se aproximar e prestar continência).

## Estado atual

Protótipo local (webcam comum) validado em hardware real. Próximo passo:
embrulhar o mesmo pipeline num nó ROS2, testado localmente antes de termos
acesso ao robô. Specs completas:

- [`docs/superpowers/specs/2026-09-10-facial-recognition-design.md`](docs/superpowers/specs/2026-09-10-facial-recognition-design.md) — protótipo standalone
- [`docs/superpowers/specs/2026-09-12-ros2-node-migration-design.md`](docs/superpowers/specs/2026-09-12-ros2-node-migration-design.md) — migração para nó ROS2

## Sobre o robô — Unitree G1 EDU

- **Compute:** NVIDIA Jetson Orin NX (100–157 TOPS conforme variante) + CPU 8 núcleos.
- **Câmera:** Intel RealSense D435i (RGB + profundidade + IMU).
- **LiDAR:** Livox MID-360.
- **SDK oficial:** ROS2 (testado/recomendado em Ubuntu 22.04 + ROS2 Humble).

Referências:
- [Página oficial do produto (unitree.com/g1)](https://www.unitree.com/g1/)
- [SDK oficial ROS2 (github.com/unitreerobotics/unitree_ros2)](https://github.com/unitreerobotics/unitree_ros2)

## Stack

Python + [InsightFace](https://github.com/deepinsight/insightface)
(detecção RetinaFace + embeddings ArcFace) via ONNX Runtime, com portagem
futura planejada para a Jetson Orin NX do robô.

## Como rodar

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
