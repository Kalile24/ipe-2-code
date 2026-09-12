# Migração para nó ROS2 — Design

Data: 2026-09-12
Contexto: Projeto IME, robô humanoide Unitree G1 EDU. Fase anterior (webcam
standalone, `docs/superpowers/specs/2026-09-10-facial-recognition-design.md`)
aprovada em teste real (Ubuntu nativo via WSL, CPU). Este documento cobre o
próximo passo: embrulhar o mesmo pipeline de reconhecimento num nó ROS2,
testado localmente (sem acesso ao robô/Jetson ainda), da forma mais fiel
possível ao ambiente real do G1.

## Pesquisa: especificações do Unitree G1 EDU

- **Compute:** Jetson Orin NX (100–157 TOPS conforme variante) + CPU 8 núcleos.
- **Câmera:** Intel RealSense D435i (RGB + profundidade + IMU).
- **LiDAR:** Livox MID-360.
- **SDK oficial (`unitree_ros2`):** testado e recomendado em **Ubuntu 22.04 +
  ROS2 Humble** (Foxy/20.04 também suportado). Usa CycloneDDS como RMW, mas
  isso só afeta os tópicos de movimento/estado do robô (`unitree_go`/
  `unitree_api`) — não tem relação com a câmera.
- **Câmera não passa pelo SDK customizado da Unitree**: os tópicos do SDK
  são de movimento/controle, não de imagem. Isso indica que a RealSense é
  exposta via o pacote **padrão** `realsense2_camera`, publicando em
  tópicos como `/camera/color/image_raw` (`sensor_msgs/Image` comum).

**Implicação de design:** Ubuntu 22.04 + ROS2 Humble é o alvo correto pro
ambiente local, e o nome de tópico de imagem padrão do nosso nó deve casar
com o do `realsense2_camera`.

## Objetivo

Ter um nó ROS2 (`face_recognition_node`) que assina uma imagem de câmera via
tópico padrão ROS2 e publica as detecções/identificações de rostos em outro
tópico padrão, testável localmente (webcam + `v4l2_camera`) sem exigir
acesso ao robô, e portável para o Jetson do G1 trocando apenas o nó de
câmera na composição do `launch`.

## Não-objetivos (fora de escopo agora)

- Lógica de navegação/interação/movimento do robô (aproximar, continência).
- Uso de profundidade 3D real (a D435i suporta, mas isso é problema de uma
  fase futura — ver nota abaixo).
- Comunicação com o SDK customizado da Unitree (`unitree_go`/`unitree_api`)
  — não é necessário pra um nó de percepção puro.
- Aceleração por GPU/TensorRT (só entra na portagem real pra Jetson).

**Nota sobre profundidade:** a D435i tem suporte ROS2 maduro
(`realsense-ros`), então estimar distância real da pessoa é viável sem
hardware adicional quando essa fase chegar. `vision_msgs/Detection2DArray`
(escolhido abaixo) já comporta uma pose 3D opcional por detecção, então a
extensão futura não vai exigir trocar o tipo de mensagem.

## Ambiente de desenvolvimento

Nova instância WSL2 com **Ubuntu 22.04 (Jammy)**, dedicada a este trabalho —
mesma versão de SO que o SDK oficial da Unitree testa/recomenda e que o
JetPack do robô usa. Evita Docker/RoboStack e qualquer camada de
compatibilidade. O projeto Python inteiro (venv, InsightFace, `core/`,
`apps/`) é recriado nessa instância, já que o nó ROS2 precisa rodar no
mesmo processo/ambiente. Bônus: Ubuntu 22.04 usa Python 3.10 por padrão,
que é o alvo nativo do `rclpy` do Humble — sem a incerteza de compatibilidade
que tivemos com o Python 3.14 do WSL anterior.

**Risco a verificar empiricamente durante a implementação:** `cv_bridge`
(pacote `apt`) é compilado contra o OpenCV do sistema/ROS; misturar isso com
`opencv-python` via `pip` no mesmo processo pode causar conflito de
binário/versão. Pode ser necessário usar o `python3-opencv` do `apt` em vez
do `opencv-python` do `pip` dentro do venv do nó ROS2. A ordem de resolução:
criar o venv com `--system-site-packages` (pra enxergar `rclpy`/`cv_bridge`/
`vision_msgs` instalados via `apt`), instalar as demais dependências do
projeto, e testar a importação conjunta antes de escrever qualquer código —
mesma abordagem de "verificar antes de assumir" que usamos com o Python
3.14 na fase anterior.

## Arquitetura e estrutura de pacotes

```
ipe-2-code/
├── pyproject.toml          # novo: torna core/ instalável (pip install -e .)
├── core/                   # sem mudança de responsabilidade
├── apps/                   # inalterado
├── tests/                  # inalterado
└── ros2_ws/
    └── src/
        └── face_recognition_ros/       # pacote ROS2 novo (ament_python)
            ├── package.xml
            ├── setup.py
            ├── face_recognition_ros/
            │   ├── face_recognition_node.py   # o nó em si
            │   └── message_builder.py         # função pura, sem rclpy
            ├── launch/
            │   └── face_recognition.launch.py
            └── test/
                └── test_message_builder.py
```

**Ajuste necessário em `core/config.py`:** os caminhos (`KNOWN_FACES_DIR`,
`DB_PATH`) hoje são relativos ao diretório de execução — funciona só porque
sempre rodamos os scripts a partir da raiz do repo. Um nó ROS2 é iniciado
pelo `ros2 launch` de qualquer diretório, então os caminhos passam a ser
ancorados via `Path(__file__).resolve().parent.parent` (raiz do repo). Um
`pyproject.toml` mínimo na raiz permite `pip install -e .` (instalação
editável — importante que seja editável, e não uma cópia, pra que
`Path(__file__)` continue apontando pro repo de verdade), tornando
`import core.face_engine` funcionar de qualquer lugar.

`core/` continua sem nenhum import de `rclpy`/`vision_msgs`/`cv_bridge` —
mesmo princípio de desacoplamento já usado com `apps/`.

## Interface do nó

**`face_recognition_node`:**
- **Assina** `sensor_msgs/msg/Image` no tópico `image_topic` (parâmetro
  ROS2, default `/camera/color/image_raw`).
- **Publica** `vision_msgs/msg/Detection2DArray` no tópico
  `detections_topic` (default `/face_recognition/detections`), um item por
  rosto detectado: bounding box (centro + largura/altura) e uma
  `ObjectHypothesisWithPose` com `class_id` = nome reconhecido (ou
  `"desconhecido"`) e `score` = confiança da similaridade de cosseno.
- Publica mesmo com **zero** rostos detectados (array vazio) — sinal de
  "vivo" pra quem consumir depois.
- Parâmetros ROS2 (default vindo de `core/config.py`): `image_topic`,
  `detections_topic`, `similarity_threshold`, `db_path`.
- QoS com fila de profundidade 1 (assinatura e publicação) — evita acumular
  frames atrasados quando o reconhecimento demora, mesmo motivo do
  `CAP_PROP_BUFFERSIZE=1` já usado no protótipo standalone.
- **Mesmo throttling do protótipo** (`RECOGNITION_INTERVAL_FRAMES`): o
  teste local também roda em CPU (WSL Ubuntu 22.04, sem GPU), então o
  gargalo do ArcFace persiste. O nó processa a cada N frames recebidos e
  reaproveita a última detecção nos frames intermediários.

**`message_builder.py`:** função pura `build_detection(bbox, name, score) ->
Detection2D`, sem depender de `rclpy` nem de estado do nó — testável com
`pytest` puro.

## Teste local (sem robô)

**Câmera local via ROS2:** pacote `v4l2_camera` (via `apt`) publica a
webcam como `sensor_msgs/Image` — nenhum código de câmera nosso. O
`launch/face_recognition.launch.py` sobe dois nós:
1. `v4l2_camera_node`, com **remapeamento** do tópico de saída
   (`/image_raw` → `/camera/color/image_raw`) — o nosso nó já fica
   configurado com o nome de tópico que vai usar no robô real, sem
   overrides de parâmetro.
2. `face_recognition_node`, ouvindo esse tópico remapeado.

Essa mesma peça de `launch` é o que, na portagem real, troca apenas o nó
`v4l2_camera_node` pelo `realsense2_camera` do robô — nada no nosso nó
muda.

**Validação manual:** `ros2 launch face_recognition_ros
face_recognition.launch.py`, e em outro terminal `ros2 topic echo
/face_recognition/detections` mostra as detecções em tempo real (nome +
confiança + bbox). Opcionalmente, `ros2 run rqt_image_view rqt_image_view`
no tópico de imagem confirma visualmente a câmera — sem visualizador
próprio.

## Tratamento de erros

- Falha ao converter a mensagem ROS pra imagem (`cv_bridge`) → loga aviso,
  descarta o frame, segue.
- Banco de identidades vazio no início → loga aviso uma vez (mesmo padrão
  do `webcam_demo.py`).
- Nenhum rosto detectado → publica array vazio (não é erro).

## Plano de testes

- `test_message_builder.py`: `pytest` puro pra `build_detection()` — bbox
  correta, `class_id`/`score` corretos, sem precisar inicializar ROS2.
- `core/` mantém sua suíte já existente, inalterada (só passa a ser
  importada via pacote instalado em vez de caminho relativo).
- Validação do nó em si (integração real com `rclpy`/tópicos) é manual,
  guiada pelo usuário com a câmera — mesmo padrão usado pro
  `webcam_demo.py`.

## Dependências novas

- `rclpy`, `sensor_msgs` — parte de qualquer instalação ROS2 Humble.
- `ros-humble-cv-bridge` (`apt`).
- `ros-humble-vision-msgs` (`apt`).
- `ros-humble-v4l2-camera` (`apt`, só pra teste local).
- `pyproject.toml` novo na raiz do repo, pra tornar `core/` instalável.
