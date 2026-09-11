CAMERA_INDEX = 0
SIMILARITY_THRESHOLD = 0.45
DET_SIZE = (640, 640)
KNOWN_FACES_DIR = "data/known_faces"
DB_PATH = "data/identity_db"
# Em CPU, o reconhecimento (ArcFace) roda bem mais devagar que a detecção
# sozinha; rodar o reconhecimento só a cada N frames mantém o vídeo fluido.
RECOGNITION_INTERVAL_FRAMES = 10
