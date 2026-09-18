from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

CAMERA_INDEX = 0
SIMILARITY_THRESHOLD = 0.45
DET_SIZE = (640, 640)
# Pacotes menores (buffalo_s, buffalo_sc) trocam acurácia por latência —
# ver docs/guides/ros2-docker.md para notas de escolha.
MODEL_NAME = "buffalo_l"
KNOWN_FACES_DIR = str(_REPO_ROOT / "data" / "known_faces")
DB_PATH = str(_REPO_ROOT / "data" / "identity_db")
# Em CPU, o reconhecimento (ArcFace) roda bem mais devagar que a detecção
# sozinha; rodar o reconhecimento só a cada N frames mantém o vídeo fluido.
RECOGNITION_INTERVAL_FRAMES = 1
