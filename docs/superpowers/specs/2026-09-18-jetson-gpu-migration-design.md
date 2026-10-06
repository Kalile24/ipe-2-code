# Portagem do nó ROS2 pro Jetson Orin NX (Unitree G1 EDU) — Design

Data: 2026-09-18 · **revisado em 2026-10-06** após revisão da documentação oficial da
Unitree e do código. A versão original assumia Ubuntu 22.04 + ROS2 Humble no robô, o que não
se confirma; o projeto passa a mirar **ROS2 Foxy** em todos os ambientes (ver "Decisão").

Contexto: o nó ROS2 `face_recognition_ros` (spec anterior:
`2026-09-12-ros2-node-migration-design.md`) já roda localmente via Docker + webcam +
`v4l2_camera`, em CPU. Este documento cobre o próximo passo: rodar esse pacote no computador
de bordo do robô, com a câmera real (Intel RealSense D435i) e a GPU da Jetson.

**Sem acesso físico ao robô no momento da escrita.** O que dá pra provar sem hardware está
provado (ver "Validado sem hardware"); o resto vira checklist do dia 1.

## Fatos do robô (documentação oficial da Unitree)

- **PC2 = JetPack 5.1.1 → Ubuntu 20.04 → Python 3.8.** A FAQ oficial publica a imagem de
  restauração de fábrica `g1_nx_Jetpack5.1.1_20250930.img.bz2`.
  https://support.unitree.com/home/en/G1_developer/FAQ
- **PC1 é fechado; PC2 (`192.168.123.164`, `unitree`/`123`) é o único aberto ao
  desenvolvedor.** A Unitree não entrega serviços no PC2 ("does not deploy services on the
  NVIDIA Jetson Orin module"): **nosso nó abre a câmera por conta própria**, via
  `realsense2_camera`. https://support.unitree.com/home/en/G1_developer/about_G1
- **O ROS não vem instalado.** A página oficial de ROS2 do G1 lista como testados Ubuntu 20.04
  + Foxy e Ubuntu 22.04 + Humble, diz que "os exemplos do repositório foram desenvolvidos em
  ROS2 Foxy" e manda o desenvolvedor instalar o Foxy pelo `apt`. O `unitree_ros2` traz as
  mensagens do G1 (`unitree_hg`). O robô fala **CycloneDDS** (domínio 0, interface da rede do
  robô). https://support.unitree.com/home/en/G1_developer/ros2_communication_routine
  · https://github.com/unitreerobotics/unitree_ros2
- **O controle do robô também pode ser feito sem ROS**, pelo `unitree_sdk2` (C++) ou
  `unitree_sdk2_python` — a via recomendada pela Unitree. Relevante para a Fase 2.
- **Tópico atual do `realsense-ros`:** `/camera/camera/color/image_raw` (namespace duplicado),
  diferente do default do nó (`/camera/color/image_raw`) — o parâmetro `image_topic` cobre.

## Decisão: ROS2 Foxy em todos os ambientes, direto no PC2

- **No robô:** o nó roda no sistema do PC2 (sem container), com ROS2 Foxy e um venv Python
  3.8 (`--system-site-packages`, para enxergar o `rclpy`/`cv_bridge` do ROS) com
  **`insightface==0.7.3`** + **`onnxruntime-gpu 1.16.0` cp38 do Jetson Zoo (JetPack 5.1.1)** +
  `numpy 1.24.4`. CUDA e TensorRT vêm instalados com o JetPack no próprio host, então a GPU não
  depende de runtime de container.
- **No desenvolvimento:** `docker/ros2.Dockerfile` usa `osrf/ros:foxy-desktop` (Ubuntu 20.04,
  Python 3.8) — o mesmo par do robô, só sem GPU. Um único alvo de ROS para o código e os testes.

Wheel GPU verificada em 2026-10-06: tag `cp38-cp38-linux_aarch64`, inclui
`libonnxruntime_providers_cuda.so` e `libonnxruntime_providers_tensorrt.so`, exige
`numpy>=1.24.4`. https://nvidia.box.com/shared/static/iizg3ggrtdkqawkmebbfixo7sce6j365.whl
(tabela oficial: https://elinux.org/Jetson_Zoo#ONNX_Runtime)

### Por que Foxy

- **Mesma versão de ROS que o SDK oficial da Unitree** (`unitree_ros2`). Na Fase 2 o nó vai
  mandar comandos de movimento ao robô; com a mesma distro não há dúvida de compatibilidade
  entre versões pela rede.
- **GPU sem incerteza de container:** no JetPack 5, container com GPU exige imagem L4T com o
  CUDA da versão exata do host; nativo, o CUDA do JetPack já está lá.
- **Custo de adaptação pequeno e verificado:** `insightface 0.7.3` e ORT cp38 seriam
  necessários de qualquer forma (Python 3.8). O que muda no código é o formato do
  `vision_msgs` (Foxy 2.0.x: `bbox.center.x`, `results[i].id`; Humble 4.x:
  `bbox.center.position.x`, `results[i].hypothesis.class_id`) e a ausência de
  `ParameterDescriptor.dynamic_typing` (no Foxy os parâmetros não têm tipo fixo). As QoS
  (`ReliabilityPolicy`, `HistoryPolicy`) existem iguais.
- Por que `insightface 0.7.3` serve: o `FaceEngine` só usa `FaceAnalysis(name, root,
  allowed_modules, providers)`, `prepare`, `get` e `face.bbox`/`det_score`/`normed_embedding` —
  API idêntica no 0.7.3 (conferido no código-fonte). E o 0.7.3 não declara `onnxruntime` como
  dependência, então não sobrescreve a wheel GPU pela de CPU.

Custos aceitos: o Foxy está sem suporte desde 2023 (sem correções); e é preciso instalá-lo no
sistema do PC2 — que é o procedimento que a própria documentação do G1 indica.

### Plano B e alternativas descartadas

- **Plano B — container L4T com Foxy** (`dustynv/ros:foxy-*-l4t-r35.*`, tag a confirmar), se
  instalar no sistema do PC2 não for possível. Mantém o mesmo alvo de código. Exige
  `--runtime nvidia` e imagem com o CUDA do JetPack 5.1.1.
- **Container Humble L4T:** exigiria manter o código em Humble e confiar em Foxy↔Humble pela
  rede na Fase 2.
- **Reflash do PC2 para JetPack 6 (Ubuntu 22.04):** sem imagem no portal oficial, carrier board
  com BSP específico, relato de perda de garantia — risco institucional para um equipamento do IME.
- **Container Ubuntu 22.04 comum:** sem GPU em JetPack 5
  (https://github.com/dusty-nv/jetson-containers/issues/802).

## Validado sem hardware

- **Container Foxy x86 (`docker/ros2.Dockerfile`, Python 3.8.10, `insightface 0.7.3`,
  `onnxruntime 1.16.0`, OpenCV 4.10):** `colcon test` do pacote — 9/9 — e a suíte `tests/` com
  o `buffalo_l` real — 35/35. Esse teste pegou um problema que também ocorreria no robô: o
  `insightface 0.7.3` puxava o OpenCV 5, que quebra o `cv_bridge` (`KeyError` ao converter
  frame); resolvido fixando `opencv-python-headless==4.10.0.84`.
- **Python 3.8.20 + `insightface 0.7.3` + `numpy 1.24.4`:** suíte `tests/` completa passando.
- Todos os módulos importam em 3.8 (`tests/test_future_annotations.py`; CI em 3.8/3.10/3.12).
- Wheel `onnxruntime-gpu 1.16.0` cp38: tags e providers conferidos (acima).

## Componentes a implementar

### `core/face_engine.py` — providers explícitos

```python
def __init__(self, det_size=(640, 640), model_name="buffalo_l",
             model_root=None, providers=None):
    kwargs = {"root": model_root} if model_root else {}
    if providers:
        kwargs["providers"] = providers
    self._app = FaceAnalysis(name=model_name, allowed_modules=["detection", "recognition"], **kwargs)
```

Sem `providers`, o InsightFace 0.7.3 usa o default dele (CUDA → CPU). No robô, o nó passa
`["TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"]` via o
parâmetro ROS2 `onnx_providers` (e argumento de launch de mesmo nome), e loga os providers
**efetivamente ativos** — o ONNX Runtime só emite `UserWarning` quando um provider pedido não
existe e segue em CPU, sem exceção.

### Instalação no PC2 (`docs/guides/jetson-deployment.md`)

```bash
# ROS2 Foxy (não vem instalado; repositório apt configurado como no guia oficial do Foxy) + pacotes do nó
sudo apt install ros-foxy-ros-base ros-foxy-cv-bridge ros-foxy-vision-msgs ros-foxy-realsense2-camera
# venv Python 3.8 enxergando o ROS do sistema
python3 -m venv --system-site-packages ~/face-venv && source ~/face-venv/bin/activate
pip install --upgrade pip                                # o pip 20.0 do Ubuntu 20.04 não vê wheels manylinux_2_27+
pip install "numpy==1.24.4" "opencv-python-headless==4.10.0.84" insightface==0.7.3
# ^ nunca instalar o pacote `onnxruntime` (CPU); OpenCV fixo em 4.x (o 5 quebra o cv_bridge)
wget -O /tmp/onnxruntime_gpu-1.16.0-cp38-cp38-linux_aarch64.whl \
  https://nvidia.box.com/shared/static/iizg3ggrtdkqawkmebbfixo7sce6j365.whl
pip install /tmp/onnxruntime_gpu-1.16.0-cp38-cp38-linux_aarch64.whl
pip install --no-deps -e .
```

Os pacotes `ros-foxy-*` vêm do repositório oficial do ROS; o Foxy está fora de suporte, então
confirmar no dia 1 que o repositório ainda os entrega (e renovar a chave GPG se o `apt` reclamar).

### Lançamento no robô

`realsense2_camera` sobe à parte e o nosso launch não sobe câmera nenhuma:

```bash
ros2 launch realsense2_camera rs_launch.py &
ros2 launch face_recognition_ros face_recognition.launch.py camera:=none \
  image_topic:=/camera/camera/color/image_raw \
  onnx_providers:="['TensorrtExecutionProvider','CUDAExecutionProvider','CPUExecutionProvider']"
```

`RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` e `CYCLONEDDS_URI` com a interface da rede do robô,
como no `unitree_ros2`, para a Fase 2.

## Checklist do dia 1 (no robô)

1. `cat /etc/nv_tegra_release` → R35.3.1 · `python3 -V` → 3.8 · `ls /opt/ros` (esperado: vazio).
2. CUDA/TensorRT no host: `ls /usr/local/cuda`, `dpkg -l | grep -i tensorrt`.
3. `rs-enumerate-devices` → D435i visível; confirmar que nenhum serviço da Unitree está
   segurando a câmera (só um processo pode abri-la).
4. No venv: `python3 -c "import onnxruntime as o; print(o.get_available_providers())"` lista
   `TensorrtExecutionProvider` e `CUDAExecutionProvider`.
5. `python3 -c "import cv_bridge, rclpy, vision_msgs"` no venv.
6. Tópico real da câmera: `ros2 topic list | grep image_raw`.
7. Latência por frame com GPU vs. CPU, com `buffalo_l` e `buffalo_sc`.
8. Memória: 16 GB compartilhados CPU/GPU com ROS2 + modelos carregados.

## Riscos abertos

1. **Pacotes `ros-foxy-*` indisponíveis** (Foxy fora de suporte) → plano B (container L4T
   Foxy) ou compilar do fonte.
2. **numpy/OpenCV do pip × `cv_bridge` do apt** (compilado contra o numpy 1.17 e o OpenCV 4 do
   Ubuntu 20.04): funciona com numpy 1.24.4 e OpenCV 4.10 no container x86; falta confirmar no
   robô, onde o JetPack traz OpenCV próprio.
3. **Ganho real da GPU não medido** — se o TensorRT EP não bastar, ver "Otimizações futuras".
4. **Primeiro uso do TensorRT EP é lento** (constrói o engine na hora); considerar o cache de
   engines do ORT (`trt_engine_cache_enable`) se o arranque incomodar.

## Otimizações futuras (documentadas, não implementadas)

- **Engines TensorRT nativos:** converter os ONNX do InsightFace com `trtexec` direto na
  Jetson (engine não é portável entre hardware/versões) e reimplementar pré/pós-processamento
  (anchors do SCRFD, alinhamento por landmarks, normalização do embedding) — o que o
  InsightFace hoje faz por nós. Só se o TensorRT EP do ONNX Runtime não for suficiente.
- **DeepStream:** pipeline NVIDIA câmera→GPU sobre GStreamer; stack inteira nova, não se
  justifica para um único nó de percepção.
