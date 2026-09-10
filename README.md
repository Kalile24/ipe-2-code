# Reconhecimento Facial — Unitree G1

Projeto institucional do IME (Instituto Militar de Engenharia), disciplina
**IPE II — Introdução a Projetos de Engenharia**.

## Objetivo

Reconhecer pessoas em vídeo ao vivo a partir de poucas fotos de referência,
como etapa inicial de um sistema de interação do robô humanoide **Unitree
G1**: o robô deve identificar uma pessoa conhecida e iniciar uma interação
apropriada (ex: reconhecer o general, se aproximar e prestar continência).

## Estado atual

Fase de prototipagem local (webcam comum), sem integração com o robô ainda.
Detalhes de arquitetura, decisões técnicas e plano de testes estão na spec:

- [`docs/superpowers/specs/2026-09-10-facial-recognition-design.md`](docs/superpowers/specs/2026-09-10-facial-recognition-design.md)

## Stack

Python + [InsightFace](https://github.com/deepinsight/insightface)
(detecção RetinaFace + embeddings ArcFace) via ONNX Runtime, com portagem
futura planejada para a Jetson Orin NX do robô.
