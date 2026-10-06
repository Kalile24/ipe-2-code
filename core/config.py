from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

CAMERA_INDEX = 0
# Ponto de partida (DeepFace usa 0,45 p/ buffalo_l; o guia do InsightFace cita 0,30–0,45).
# O valor CERTO para as pessoas e a câmera deste projeto sai de
# `python -m scripts.calibrar_limiar` depois do cadastro.
SIMILARITY_THRESHOLD = 0.45
DET_SIZE = (640, 640)
# Pacotes menores (buffalo_s, buffalo_sc) trocam acurácia por latência —
# ver docs/guides/ros2-docker.md para notas de escolha.
MODEL_NAME = "buffalo_l"
# Diretório raiz dos modelos do InsightFace (None = padrão ~/.insightface). Onde não há
# internet, aponte para uma pasta pré-carregada com models/<MODEL_NAME>/*.onnx. A imagem
# Docker exporta INSIGHTFACE_ROOT=/opt/insightface e é ESTA linha que a lê — sem ela a
# variável seria um controle morto e o nó tentaria baixar da internet.
MODEL_ROOT = os.environ.get("INSIGHTFACE_ROOT") or None
KNOWN_FACES_DIR = str(_REPO_ROOT / "data" / "known_faces")
DB_PATH = str(_REPO_ROOT / "data" / "identity_db")
# Em CPU, o reconhecimento (ArcFace) roda bem mais devagar que a detecção
# sozinha; rodar o reconhecimento só a cada N frames mantém o vídeo fluido.
RECOGNITION_INTERVAL_FRAMES = 1
