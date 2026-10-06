# Portagem do nó ROS2 pro Jetson Orin NX (Unitree G1 EDU) — Design

Data: 2026-09-18 · **revisado em 2026-10-06** após revisão da documentação oficial da
Unitree e do código (a versão anterior assumia Ubuntu 22.04 + ROS2 Humble nativos no robô,
o que não se confirma — ver "Fatos do robô").

Contexto: o nó ROS2 `face_recognition_ros` (spec anterior:
`2026-09-12-ros2-node-migration-design.md`) já está validado localmente — build, testes e
reconhecimento real via Docker + webcam + `v4l2_camera`, em CPU. Este documento cobre o
próximo passo: rodar esse pacote no computador de bordo do robô, com a câmera real (Intel
RealSense D435i) e a GPU da Jetson.

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
- **Os exemplos ROS2 oficiais são Foxy**; o robô fala **CycloneDDS** (domínio 0, interface
  da rede do robô). https://support.unitree.com/home/en/G1_developer/ros2_communication_routine
  · README de https://github.com/unitreerobotics/unitree_ros2
- **`vision_msgs` muda de formato entre Foxy e Humble.** Foxy (2.0.0):
  `bbox.center.x`, `results[i].id`. Humble (4.1.1): `bbox.center.position.x`,
  `results[i].hypothesis.class_id`. Nosso `message_builder.py` é Humble.
- **Tópico atual do `realsense-ros`:** `/camera/camera/color/image_raw` (namespace duplicado),
  diferente do default do nó (`/camera/color/image_raw`) — o parâmetro `image_topic` cobre.

Consequências técnicas:

- Não existe Humble binário para Ubuntu 20.04. **Humble em JetPack 5 = Humble compilado do
  fonte em Focal, com `rclpy` em Python 3.8** (imagens `dustynv/ros:humble-*-l4t-r35.x`).
- **Container Ubuntu 22.04 não tem GPU em JetPack 5**: desde o JP 5.0 o runtime NVIDIA injeta
  só os drivers do host; CUDA/TensorRT precisam estar dentro da imagem, e isso só é suportado
  em imagens L4T (Ubuntu 20.04). Há falha reproduzida num Orin NX 16 GB:
  https://github.com/dusty-nv/jetson-containers/issues/802
- `insightface==2.0` exige Python ≥ 3.10 — **não roda no Python 3.8** do `rclpy`.

## Decisão

**Um container, um processo, Python 3.8:**

- Base `dustynv/ros:humble-ros-base-l4t-r35.3.1` (Ubuntu 20.04; Humble do fonte; CUDA 11.4 e
  TensorRT 8.5.2 dentro da imagem; CycloneDDS). Roda no PC2 de fábrica com
  `--runtime nvidia --network host`, câmera por `--device`/`--privileged`. **O host não é
  alterado** (sem reflash).
- Inferência no mesmo processo do nó: **`insightface==0.7.3`** (última versão para Python
  3.8) + **`onnxruntime-gpu 1.16.0` cp38 do Jetson Zoo para JetPack 5.1.1** + `numpy 1.24.4`.
  Wheel verificada em 2026-10-06: tag `cp38-cp38-linux_aarch64`, inclui
  `libonnxruntime_providers_cuda.so` e `libonnxruntime_providers_tensorrt.so`, exige
  `numpy>=1.24.4`. https://nvidia.box.com/shared/static/iizg3ggrtdkqawkmebbfixo7sce6j365.whl
  (tabela oficial: https://elinux.org/Jetson_Zoo#ONNX_Runtime)
- O `docker/ros2.Dockerfile` (x86, Ubuntu 22.04) continua como ambiente de desenvolvimento.

Por que `insightface 0.7.3` serve: o `FaceEngine` só usa `FaceAnalysis(name, root,
allowed_modules, providers)`, `prepare(ctx_id, det_size)`, `get(img)` e
`face.bbox`/`det_score`/`normed_embedding` — API idêntica no 0.7.3 (conferido no código-fonte
do pacote). E o 0.7.3 **não declara `onnxruntime` como dependência**, então instalá-lo não
sobrescreve a wheel GPU pela de CPU (o 2.0 declara, e o pip troca o módulo sem erro).

### Alternativas descartadas

- **Nativo no host (Foxy, Python 3.8):** exigiria instalar e manter ROS2 no host
  (a Unitree não entrega) e uma camada de compatibilidade para o `vision_msgs` do Foxy.
- **Reflash do PC2 para JetPack 6 (Ubuntu 22.04):** a imagem não está no portal oficial, a
  carrier board da Unitree exige BSP específico e há relato de perda de garantia — risco
  institucional para um equipamento do IME. Fica como último recurso.
- **Dois processos (nó em 3.8 ↔ inferência em 3.10 com `insightface 2.0`, via IPC):**
  preserva o 2.0 ao custo de um serviço de inferência, serialização de frames entre
  processos, um segundo interpretador e um ambiente onde qualquer `pip install` pode trocar o
  ORT GPU pelo de CPU sem erro. Não usamos nada do 2.0 que o 0.7.3 não tenha.
- **Container Ubuntu 22.04 (`ros:humble` oficial):** sem GPU em JetPack 5.

## Validado sem hardware

- **Suíte completa em Python 3.8.20 + `insightface 0.7.3` + `numpy 1.24.4` (x86, CPU):
  35 passed**, incluindo os testes que carregam o `buffalo_l` real (detecção e cadastro).
  Comando: `python:3.8` com `pip install 'numpy<1.25' onnxruntime opencv-python-headless
  insightface==0.7.3 pytest`.
- Todos os módulos importam em 3.8 (`from __future__ import annotations` em todos;
  `tests/test_future_annotations.py` guarda isso; CI roda 3.8/3.10/3.12).
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

Sem `providers`, o InsightFace usa o default dele (no 0.7.3: CUDA → CPU). No robô, o nó
passa `["TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"]` via
o parâmetro ROS2 `onnx_providers` (e argumento de launch de mesmo nome). Depois do
`prepare()`, o nó loga os providers **efetivamente ativos** de cada sessão — o ONNX Runtime
só emite `UserWarning` quando um provider pedido não existe e segue em CPU, sem exceção.

### `docker/ros2-jetson.Dockerfile` — esboço

```dockerfile
FROM dustynv/ros:humble-ros-base-l4t-r35.3.1
# A imagem (dez/2023) traz a chave GPG do ROS expirada: renovar antes de qualquer apt.
RUN curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
      -o /usr/share/keyrings/ros-archive-keyring.gpg
# Dependências do insightface 0.7.3 + a wheel GPU. numpy 1.24.4: última p/ Python 3.8 e
# exigida pela wheel. Nunca instalar o pacote `onnxruntime` (CPU) — ele sobrescreve o módulo.
RUN pip3 install "numpy==1.24.4" insightface==0.7.3 && \
    wget -q -O /tmp/onnxruntime_gpu-1.16.0-cp38-cp38-linux_aarch64.whl \
      https://nvidia.box.com/shared/static/iizg3ggrtdkqawkmebbfixo7sce6j365.whl && \
    pip3 install /tmp/onnxruntime_gpu-1.16.0-cp38-cp38-linux_aarch64.whl && rm /tmp/*.whl
# Modelos pré-baixados (o robô não tem internet): ver INSIGHTFACE_ROOT em core/config.py.
ENV INSIGHTFACE_ROOT=/opt/insightface
```

A construir e testar em arm64 emulado antes do dia 1; o `realsense2_camera` pode não vir na
imagem (compilar `librealsense` + `realsense-ros` do fonte nesse caso).

### Lançamento no robô

`realsense2_camera` sobe à parte e o nosso launch não sobe câmera nenhuma:

```bash
ros2 launch face_recognition_ros face_recognition.launch.py camera:=none \
  image_topic:=/camera/camera/color/image_raw model_root:=/opt/insightface \
  onnx_providers:="['TensorrtExecutionProvider','CUDAExecutionProvider','CPUExecutionProvider']"
```

### `docs/guides/jetson-deployment.md`

Passo a passo de build/execução no PC2 + o checklist do dia 1 abaixo + troubleshooting.

## Checklist do dia 1 (no robô)

1. `cat /etc/nv_tegra_release` → R35.3.1 · `python3 -V` → 3.8.
2. `docker info | grep -i runtime` → `nvidia` (idealmente `default-runtime: nvidia` em
   `/etc/docker/daemon.json`).
3. `rs-enumerate-devices` → D435i visível. Confirmar que nenhum serviço da Unitree está
   segurando a câmera (só um processo pode abri-la).
4. Dentro do container: `python3 -c "import onnxruntime as o; print(o.get_available_providers())"`
   lista `TensorrtExecutionProvider` e `CUDAExecutionProvider`.
5. `cv_bridge`/`cv2` importam (dependem de libs Tegra montadas do host pelo runtime).
6. Tópico real da câmera: `ros2 topic list | grep image_raw`.
7. Latência por frame com GPU vs. CPU, com `buffalo_l` e `buffalo_sc`.
8. Memória: 16 GB compartilhados CPU/GPU com Humble + modelos carregados.

## Riscos abertos

1. **`cv2` duplicado no container:** o `insightface` usa o `cv2` do pip; a imagem dusty traz
   OpenCV próprio, usado pelo `cv_bridge`. Mesma classe de conflito já vista no Docker x86
   (numpy). Verificar no build emulado; se conflitar, usar só o OpenCV da imagem.
2. **`realsense2_camera` ausente na imagem** → compilar do fonte.
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
