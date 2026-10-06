# Instalação no robô (Jetson Orin NX do Unitree G1 EDU) — guia

Passo a passo para rodar o `face_recognition_ros` no computador de desenvolvimento do robô
(**PC2**), com a câmera RealSense D435i e a GPU da Jetson. Decisões e motivos: spec
[`2026-09-18-jetson-gpu-migration-design.md`](../superpowers/specs/2026-09-18-jetson-gpu-migration-design.md).

**Estado deste guia (2026-10-06): ainda não executado no robô.** O que já foi verificado:
- todo o fluxo de Python/ROS (venv, versões, `colcon`, testes) num container x86 com o mesmo
  Ubuntu 20.04 / Python 3.8 / ROS2 Foxy do PC2 (`docker/ros2.Dockerfile`);
- os pacotes `ros-foxy-*` usados aqui existem para ARM64 no repositório oficial do ROS;
- a wheel `onnxruntime-gpu` da Jetson (tag `cp38-cp38-linux_aarch64`, com providers CUDA e TensorRT).

O que só o robô confirma está marcado com **[dia 1]**.

## Visão geral

| | |
|---|---|
| PC2 | Jetson Orin NX, JetPack 5.1.1 (Ubuntu 20.04, Python 3.8), `192.168.123.164`, usuário `unitree` / senha `123` |
| ROS | ROS2 **Foxy**, instalado por nós (não vem no robô) |
| Python | venv `~/face-venv`, enxergando o ROS do sistema |
| Inferência | `insightface 0.7.3` + `onnxruntime-gpu 1.16.0` (wheel NVIDIA) |
| Câmera | `realsense2_camera` (D435i na USB do PC2), lançado à parte |

Os comandos abaixo rodam **no PC2**, via SSH (`ssh unitree@192.168.123.164`) a partir de um
computador na rede do robô (`192.168.123.x`). O PC2 precisa de internet (Wi-Fi) para `apt` e
`pip`.

## 1. Conferir o sistema [dia 1]

```bash
cat /etc/nv_tegra_release         # esperado: R35 (REVISION: 3.1) = JetPack 5.1.1
python3 -V                        # esperado: 3.8.x
ls /opt/ros 2>/dev/null           # esperado: vazio (o ROS não vem instalado)
ls /usr/local/cuda/bin/nvcc && dpkg -l | grep -i -E "tensorrt|libnvinfer" | head -3
free -h                           # 16 GB compartilhados CPU/GPU
```

Se o JetPack não for o 5.1.1, a wheel do passo 4 muda — ver a tabela do Jetson Zoo nas
referências.

## 2. Instalar o ROS2 Foxy

Mesmo procedimento do guia oficial do Foxy, que a documentação ROS2 do G1 indica:

```bash
sudo apt update && sudo apt install -y curl software-properties-common
sudo add-apt-repository universe
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
  -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" \
  | sudo tee /etc/apt/sources.list.d/ros2.list > /dev/null
sudo apt update
sudo apt install -y ros-foxy-ros-base python3-colcon-common-extensions \
  ros-foxy-cv-bridge ros-foxy-vision-msgs ros-foxy-realsense2-camera ros-foxy-rmw-cyclonedds-cpp \
  python3-venv python3-dev
```

`python3-dev` é para o `insightface 0.7.3`, que compila uma extensão C++ na instalação.

## 3. Baixar o código

```bash
git clone https://github.com/Kalile24/ipe-2-code.git ~/ipe-2-code
cd ~/ipe-2-code
```

## 4. Ambiente Python (venv)

```bash
source /opt/ros/foxy/setup.bash
python3 -m venv --system-site-packages ~/face-venv   # enxerga rclpy, cv_bridge etc. do ROS
source ~/face-venv/bin/activate
pip install --upgrade pip                            # o pip 20.0 do Ubuntu 20.04 não acha wheels novas
pip install "setuptools==58.2.0"                     # o colcon do Foxy quebra com setuptools novo
pip install "numpy==1.24.4" "opencv-python-headless==4.10.0.84" insightface==0.7.3
wget -O /tmp/onnxruntime_gpu-1.16.0-cp38-cp38-linux_aarch64.whl \
  https://nvidia.box.com/shared/static/iizg3ggrtdkqawkmebbfixo7sce6j365.whl
pip install /tmp/onnxruntime_gpu-1.16.0-cp38-cp38-linux_aarch64.whl
pip install --no-deps -e .                           # o pacote core/ deste repositório
```

O nome do arquivo `.whl` importa: o pip recusa a wheel se o nome não tiver as tags
`cp38-cp38-linux_aarch64`.

Conferir [dia 1]:

```bash
python3 -c "import onnxruntime as o; print(o.__version__, o.get_available_providers())"
# esperado: 1.16.0 ['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']
python3 -c "import cv2; print(cv2.__version__, cv2.CV_8UC3)"     # esperado: 4.10.0 16
python3 -c "import rclpy, cv_bridge, vision_msgs, insightface; print('ok')"
```

**Regra do venv:** nunca `pip install onnxruntime` (pacote de CPU: sobrescreve o módulo da
wheel GPU sem erro) e nada que puxe o OpenCV 5 (quebra o `cv_bridge`). Para instalar algo
novo, prefira `pip install --no-deps <pacote>` e rode a conferência acima depois.

## 5. Modelos e cadastro

Na primeira execução o InsightFace baixa o modelo (~300 MB) para `~/.insightface`. Sem
internet no PC2, copie do seu computador:

```bash
# no SEU computador
ssh unitree@192.168.123.164 mkdir -p .insightface/models
scp -r ~/.insightface/models/buffalo_l ~/.insightface/models/buffalo_sc \
  unitree@192.168.123.164:.insightface/models/
```

O banco de identidades (`data/identity_db_<modelo>.npz/.json`) pode ser gerado no seu
computador e copiado — os embeddings dependem só do modelo, não da máquina:

```bash
# no SEU computador, na raiz do repositório
.venv/bin/python -m apps.enroll --model buffalo_l
scp data/identity_db_buffalo_l.* unitree@192.168.123.164:ipe-2-code/data/
```

(Ou rode `python -m apps.enroll` direto no PC2, com o venv ativo, depois de copiar
`data/known_faces/`.)

## 6. Compilar o pacote ROS2

```bash
source /opt/ros/foxy/setup.bash
source ~/face-venv/bin/activate
cd ~/ipe-2-code/ros2_ws
python3 -m colcon build --symlink-install
source install/setup.bash
```

**Use `python3 -m colcon`, não `colcon`.** Com o `colcon` puro, o executável do nó sai
apontando para o Python do sistema (`/usr/bin/python3`), que não enxerga o `insightface` nem a
wheel GPU do venv. Confira: `head -1 install/face_recognition_ros/lib/face_recognition_ros/face_recognition_node`
deve mostrar `#!/home/unitree/face-venv/bin/python3`.

## 7. Rodar (três terminais, todos com os `source` do passo 6)

**Terminal A — câmera:**

```bash
ros2 launch realsense2_camera rs_launch.py
```

**Terminal B — confirmar o tópico da imagem [dia 1]:**

```bash
ros2 topic list | grep image_raw
```

A versão do Foxy (`realsense2_camera` 4.51) deve publicar em `/camera/color/image_raw`; versões
mais novas usam `/camera/camera/color/image_raw`. Use o que aparecer abaixo.

**Terminal B — reconhecimento:**

```bash
ros2 launch face_recognition_ros face_recognition.launch.py camera:=none \
  image_topic:=/camera/color/image_raw \
  onnx_providers:=TensorrtExecutionProvider,CUDAExecutionProvider,CPUExecutionProvider
```

No log, procure a linha `providers ativos: {...}` — ela tem que listar
`TensorrtExecutionProvider` (ou ao menos `CUDAExecutionProvider`). Se aparecer
`providers pedidos mas NÃO ativos`, a GPU não está em uso (ver "Problemas comuns"). A primeira
execução com TensorRT demora mais: ele monta o engine otimizado na hora.

**Terminal C — ver as detecções:**

```bash
python3 ~/ipe-2-code/scripts/watch_detections.py     # imprime "nome: score" por rosto
```

Para comparar modelos, repita com `model_name:=buffalo_sc` no terminal B (o banco desse modelo
precisa existir — passo 5).

## 8. Falar com o robô (Fase 2)

Para o reconhecimento sozinho não é preciso. Quando o nó for conversar com o robô (movimento,
estado), use o CycloneDDS na interface da rede do robô, como no `unitree_ros2` oficial:

```bash
ip -br addr          # [dia 1] descobrir o nome da interface na rede 192.168.123.x (ex: eth0)
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI='<CycloneDDS><Domain><General><Interfaces>
  <NetworkInterface name="eth0" priority="default" multicast="default" />
</Interfaces></General></Domain></CycloneDDS>'
```

## Checklist do dia 1

1. Sistema conferido (passo 1).
2. Providers GPU disponíveis no venv e `cv2.CV_8UC3 == 16` (passo 4).
3. Shebang do nó aponta para o venv (passo 6).
4. `rs-enumerate-devices` mostra a D435i, e nenhum outro processo está com a câmera aberta.
5. Tópico real da imagem (passo 7).
6. Log com `TensorrtExecutionProvider`/`CUDAExecutionProvider` ativos.
7. Latência por frame: GPU vs. CPU (`onnx_providers:=CPUExecutionProvider`), com `buffalo_l` e
   `buffalo_sc`.
8. Memória livre com tudo rodando (`free -h`, `tegrastats`).

## Problemas comuns

- **Nó não acha `insightface`/`onnxruntime` (`ModuleNotFoundError`)** — o pacote foi
  compilado com `colcon` puro. Refaça o passo 6 com `python3 -m colcon build`, com o venv ativo.
- **`KeyError: 16` ao converter frame** — o OpenCV 5 entrou no venv (o OpenCV 5 mudou o código
  `CV_8UC3` de 16 para 64 e o `cv_bridge` espera 16). Corrija com
  `pip install --no-deps "opencv-python-headless==4.10.0.84"` e remova outros `opencv-*`
  (`pip list | grep -i opencv`).
- **`providers ativos` só com CPU** — confira `pip list | grep -i onnxruntime`: deve haver só
  `onnxruntime-gpu 1.16.0`. Se aparecer `onnxruntime` (CPU), desinstale os dois e reinstale a
  wheel GPU. Se a wheel estiver certa, confira se as bibliotecas do TensorRT do JetPack existem
  (`ls /usr/lib/aarch64-linux-gnu/libnvinfer*`).
- **`AttributeError: _ARRAY_API not found` / `numpy.core.multiarray failed to import`** — entrou
  numpy 2. A wheel GPU e o `cv_bridge` foram compilados contra numpy 1:
  `pip install "numpy==1.24.4"`.
- **`No matching distribution found` no pip** — pip antigo: `pip install --upgrade pip`.
- **`apt update` reclama de chave GPG do ROS** — baixe de novo a chave (o `curl` do passo 2).
- **Câmera não abre / "device busy"** — só um processo pode usar a D435i por vez. Feche outros
  usos (`ps aux | grep -i realsense`) antes de subir o `realsense2_camera`.

## Referências

- Documentação oficial do G1: [FAQ (imagem de fábrica do PC2)](https://support.unitree.com/home/en/G1_developer/FAQ) ·
  [ROS2 Communication Routine](https://support.unitree.com/home/en/G1_developer/ros2_communication_routine) ·
  [About G1 (PC1/PC2)](https://support.unitree.com/home/en/G1_developer/about_G1)
- [Instalação do ROS2 Foxy (Debian)](https://docs.ros.org/en/foxy/Installation/Ubuntu-Install-Debians.html)
- [unitree_ros2](https://github.com/unitreerobotics/unitree_ros2) · [unitree_sdk2_python](https://github.com/unitreerobotics/unitree_sdk2_python)
- [Jetson Zoo — wheels do ONNX Runtime por JetPack](https://elinux.org/Jetson_Zoo#ONNX_Runtime) ·
  [TensorRT Execution Provider](https://onnxruntime.ai/docs/execution-providers/TensorRT-ExecutionProvider.html)
- [realsense-ros](https://github.com/IntelRealSense/realsense-ros)
