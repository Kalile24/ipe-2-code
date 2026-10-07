# Instalação no robô (Jetson Orin NX do Unitree G1 EDU) — guia

Passo a passo para rodar o `face_recognition_ros` no computador de desenvolvimento do robô
(**PC2**), com a câmera RealSense D435i e a GPU da Jetson. Decisões e motivos: spec
[`2026-09-18-jetson-gpu-migration-design.md`](../superpowers/specs/2026-09-18-jetson-gpu-migration-design.md).

**Estado deste guia:** o PC2 do robô do IME foi inspecionado em **2026-10-07** (só leitura —
seção "Estado do robô"); a instalação dos passos 2 em diante **ainda não foi executada**. Além
disso, todo o fluxo de Python/ROS (venv, versões, `colcon`, testes) foi verificado num container
x86 com o mesmo Ubuntu 20.04 / Python 3.8 / ROS2 Foxy (`docker/ros2.Dockerfile`). O que só se
confirma rodando no robô está marcado com **[robô]**.

## Estado do robô (inspeção de 2026-10-07)

| | |
|---|---|
| Acesso | SSH `unitree@192.168.123.164` (senha padrão `123`, também a do `sudo`); hostname `ubuntu` |
| Sistema | JetPack 5.1.1 (`R35 REVISION: 3.1`), Ubuntu 20.04.6, kernel 5.10.104-tegra, Python 3.8.10 |
| GPU | CUDA (`/usr/local/cuda`) e TensorRT 8.5.2 instalados |
| Recursos | 15 GB de RAM (12 livres em repouso), disco de 1,9 TB (3% usado) |
| Câmera | D435i na USB (`8086:0b3a`), `/dev/video0`–`5`; **livre** (nenhum processo com ela aberta) |
| Rede | `eth0` = 192.168.123.164 (conexão `unitree1`, rede interna do robô); `wlan0` presente, desconectado |
| ROS | **Foxy e Noetic já instalados** em `/opt/ros` (pelo instalador comunitário fishros); repositório apt do ROS configurado e com chave válida |
| Python global | `numpy 1.24.4`, `opencv-python 4.13`, `torch 2.4.1`, `unitree_sdk2py 1.0.1`, `cyclonedds 0.10.2`, `pyrealsense2 2.55.1` |
| Outros | Docker 24; desktop Ubuntu (GNOME) com **NoMachine** 8.9.1 ativo na porta 4000 |

Pacotes ROS do nosso nó: `ros-foxy-ros-base`, `ros-foxy-cv-bridge`, `ros-foxy-rmw-cyclonedds-cpp`,
`python3-colcon-common-extensions` e `python3-dev` **já instalados**; faltam
`ros-foxy-vision-msgs`, `ros-foxy-realsense2-camera`, `ros-foxy-librealsense2` e `python3-venv`
(passo 2).

### Outro projeto que já roda neste robô (`~/hhhh`) — regras de convivência

- O serviço `unitree-start-joystick.service` sobe no boot, conversa com o robô por DDS na
  `eth0` e espera o botão **START** do controle. O START dispara `~/hhhh/iniciar_robo.sh`, que
  liga uma caixa Bluetooth, servidores de voz (Piper/Whisper), um assistente de voz
  (`assistente.py`) e o `movimentos_militares.py` — sentido, descansar, apresentação e
  **continência (`F1 + B`)**, com poses gravadas em `~/hhhh/poses/`.
- Nada desse projeto usa a câmera.
- **Não desative nem edite esse serviço** sem falar com quem o mantém.
- **Nunca rode `pip install` fora do nosso venv** (nem com `sudo`): esses scripts usam o
  Python global (`/usr/bin/python3`), e trocar o numpy/OpenCV de lá pode quebrá-los.
- **Fase 2:** a continência já existe; o reconhecimento vai precisar *dispará-la*, combinado com
  o autor — dois programas comandando o braço ao mesmo tempo é perigoso.

### O prompt do fishros

A cada login, o terminal pergunta `ros:foxy(1) noetic(2) ?`. **Responda sempre `1`.** Carregar o
Noetic (ROS 1) no mesmo terminal do nosso ambiente mistura ROS 1 e ROS 2. Não altere o
`~/.bashrc`: o robô é compartilhado e alguém pode usar o Noetic.

## 0. Acesso ao robô

**SSH pelo cabo:** ligue seu computador na rede do robô (IP fixo na faixa `192.168.123.x`, ex.:
`.99`) e `ssh unitree@192.168.123.164`.

**Wi-Fi (para dispensar o cabo)** — método da FAQ oficial do G1, rodado no PC2 ainda pelo cabo:

```bash
sudo nmcli radio wifi on
nmcli device wifi list
sudo nmcli device wifi connect "NOME_DA_REDE" password "SENHA"
ip -br addr show wlan0          # o IP que o robô pegou; use-o no ssh
```

A conexão fica salva e volta sozinha no boot. Não mexa na conexão da `eth0`: é por ela que o
PC2 fala com o computador de controle do robô. Redes de campus costumam bloquear a comunicação
entre aparelhos ou exigir login institucional (WPA2-Enterprise); nesses casos use um roteador
próprio ou o hotspot de um celular (o log do robô mostra que já foi usado assim). O IP do Wi-Fi
pode mudar a cada boot.

**Área de trabalho remota (NoMachine):** instale o cliente no seu computador
(https://www.nomachine.com/download) e conecte em `192.168.123.164` (ou no IP do Wi-Fi), porta
`4000`, protocolo NX, usuário `unitree`. Sem monitor no robô, escolha criar uma área de trabalho
virtual. Útil para ver a câmera (`rqt_image_view`); feche a sessão quando não estiver usando,
porque consome memória e GPU.

## 1. Conferir o sistema

Já conferido em 2026-10-07 (tabela acima). Para repetir (ex.: depois de uma restauração de
fábrica):

```bash
cat /etc/nv_tegra_release         # esperado: R35 (release), REVISION: 3.1 = JetPack 5.1.1
python3 -V                        # esperado: 3.8.x
ls /opt/ros                       # neste robô: foxy noetic
lsusb | grep -i intel             # a D435i
fuser -v /dev/video*              # vazio = câmera livre
```

## 2. Instalar o que falta

```bash
sudo apt update
sudo apt install -y ros-foxy-vision-msgs ros-foxy-realsense2-camera ros-foxy-librealsense2 python3-venv
```

Não rode `sudo apt upgrade` no sistema todo: ele atualizaria também os pacotes da NVIDIA
(`nvidia-l4t-*`: kernel, drivers, bootloader) que formam a base validada pela Unitree.

**Robô restaurado de fábrica (sem `/opt/ros`):** a imagem oficial não traz ROS. Instale o Foxy
pelo procedimento do guia oficial (o que a documentação ROS2 do G1 indica) e depois os pacotes
acima:

```bash
sudo apt install -y curl software-properties-common && sudo add-apt-repository universe
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
  -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" \
  | sudo tee /etc/apt/sources.list.d/ros2.list > /dev/null
sudo apt update
sudo apt install -y ros-foxy-ros-base python3-colcon-common-extensions ros-foxy-cv-bridge \
  ros-foxy-rmw-cyclonedds-cpp python3-dev
```

## 3. Baixar o código

```bash
git clone https://github.com/Kalile24/ipe-2-code.git ~/ipe-2-code
cd ~/ipe-2-code
```

## 4. Ambiente Python (venv)

O venv fica dentro do repositório (`.venv`, já no `.gitignore`): tudo o que é nosso no robô
fica em `~/ipe-2-code`. Responda `1` ao prompt do fishros e **não carregue o
`~/ros2_ws/install/setup.bash`** — é um workspace de outra pessoa com um `realsense-ros`
compilado do fonte, que passaria por cima do instalado pelo `apt` (e mudaria o tópico da câmera).

```bash
cd ~/ipe-2-code
source /opt/ros/foxy/setup.bash
python3 -m venv --system-site-packages .venv         # enxerga rclpy, cv_bridge etc. do ROS
source .venv/bin/activate
pip install --upgrade pip                            # o pip 20.0 do Ubuntu 20.04 não acha wheels novas
pip install "setuptools==58.2.0"                     # o colcon do Foxy quebra com setuptools novo
pip install "numpy==1.24.4" "opencv-python-headless==4.10.0.84" insightface==0.7.3
wget -O /tmp/onnxruntime_gpu-1.16.0-cp38-cp38-linux_aarch64.whl \
  https://nvidia.box.com/shared/static/iizg3ggrtdkqawkmebbfixo7sce6j365.whl
pip install /tmp/onnxruntime_gpu-1.16.0-cp38-cp38-linux_aarch64.whl
pip install --no-deps -e .                           # o pacote core/ deste repositório
```

Neste robô o `numpy 1.24.4` global já é a versão certa (o pip vai dizer "already satisfied"). O
OpenCV 4.10 instalado no venv tem prioridade sobre o 4.13 global; ele é necessário porque, sem a
versão fixa, o `insightface` puxa o OpenCV 5, que quebra o `cv_bridge`. O nome do arquivo `.whl`
importa: o pip recusa a wheel se o nome não tiver `cp38-cp38-linux_aarch64`.

Conferir [robô]:

```bash
python3 -c "import onnxruntime as o; print(o.__version__, o.get_available_providers())"
# esperado: 1.16.0 ['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']
python3 -c "import cv2; print(cv2.__version__, cv2.CV_8UC3)"     # esperado: 4.10.0 16
python3 -c "import rclpy, cv_bridge, vision_msgs, insightface; print('ok')"
```

**Regra do venv:** nunca `pip install onnxruntime` (pacote de CPU: sobrescreve o módulo da
wheel GPU sem erro) e nada que puxe o OpenCV 5. Para instalar algo novo, prefira
`pip install --no-deps <pacote>` e rode a conferência acima depois.

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
source ~/ipe-2-code/.venv/bin/activate
cd ~/ipe-2-code/ros2_ws
python3 -m colcon build --symlink-install
source install/setup.bash
```

**Use `python3 -m colcon`, não `colcon`.** Com o `colcon` puro, o executável do nó sai
apontando para o Python do sistema (`/usr/bin/python3`), que não enxerga o `insightface` nem a
wheel GPU do venv. Confira: `head -1 install/face_recognition_ros/lib/face_recognition_ros/face_recognition_node`
deve mostrar `#!/home/unitree/ipe-2-code/.venv/bin/python3`.

## 7. Rodar (três terminais, todos com os `source` do passo 6)

**Atalho:** `~/ipe-2-code/scripts/robo_tmux.sh` abre a sessão tmux `face` com os três terminais
abaixo já rodando (ambiente Foxy + CycloneDDS + venv, sem o prompt do fishros); entre com
`tmux attach -t face`. Os passos manuais seguem abaixo.

**Terminal A — câmera:**

```bash
ros2 launch realsense2_camera rs_launch.py
```

**Terminal B — confirmar o tópico da imagem [robô]:**

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
estado), use o CycloneDDS na interface da rede do robô — neste PC2, `eth0` (a mesma que o
serviço do joystick usa) —, como no `unitree_ros2` oficial:

```bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI='<CycloneDDS><Domain><General><Interfaces>
  <NetworkInterface name="eth0" priority="default" multicast="default" />
</Interfaces></General></Domain></CycloneDDS>'
```

## Checklist

Já confirmado em 2026-10-07: JetPack 5.1.1 / Python 3.8; CUDA e TensorRT; D435i visível e
livre; memória e disco; interface `eth0`; ROS2 Foxy instalado.

Falta [robô]:

1. Pacotes do passo 2 instalados.
2. Providers GPU disponíveis no venv e `cv2.CV_8UC3 == 16` (passo 4).
3. Shebang do nó aponta para o venv (passo 6).
4. Tópico real da imagem (passo 7).
5. Log com `TensorrtExecutionProvider`/`CUDAExecutionProvider` ativos.
6. Latência por frame: GPU vs. CPU (`onnx_providers:=CPUExecutionProvider`), com `buffalo_l` e
   `buffalo_sc`.
7. Memória livre com tudo rodando (`free -h`, `tegrastats`).

## Problemas comuns

- **Nó não acha `insightface`/`onnxruntime` (`ModuleNotFoundError`)** — o pacote foi
  compilado com `colcon` puro. Refaça o passo 6 com `python3 -m colcon build`, com o venv ativo.
- **`KeyError: 16` ao converter frame** — o OpenCV 5 entrou no venv (o OpenCV 5 mudou o código
  `CV_8UC3` de 16 para 64 e o `cv_bridge` espera 16). Corrija com
  `pip install --no-deps "opencv-python-headless==4.10.0.84"` e remova outros `opencv-*` do venv
  (`pip list | grep -i opencv`).
- **`providers ativos` só com CPU** — confira `pip list | grep -i onnxruntime`: deve haver só
  `onnxruntime-gpu 1.16.0`. Se aparecer `onnxruntime` (CPU), desinstale os dois e reinstale a
  wheel GPU. Se a wheel estiver certa, confira se as bibliotecas do TensorRT do JetPack existem
  (`ls /usr/lib/aarch64-linux-gnu/libnvinfer*`).
- **`AttributeError: _ARRAY_API not found` / `numpy.core.multiarray failed to import`** — entrou
  numpy 2. A wheel GPU e o `cv_bridge` foram compilados contra numpy 1:
  `pip install "numpy==1.24.4"`.
- **Erros estranhos de import do ROS** — o terminal carregou o Noetic (resposta `2` no prompt do
  fishros). Abra outro terminal e responda `1`.
- **`No matching distribution found` no pip** — pip antigo: `pip install --upgrade pip`.
- **`Unable to locate package ros-foxy-...` mesmo depois do `apt update`** — a lista do
  repositório do ROS em cache ficou vazia (`ls -la /var/lib/apt/lists/ | grep packages.ros.org`
  mostra o `..._Packages` com 0 bytes), de um `apt update` feito sem internet. Como o Foxy não
  muda mais, o `apt update` acha que está em dia e não baixa de novo. Apague o cache e baixe
  tudo: `sudo rm -rf /var/lib/apt/lists/* && sudo apt update` (só índices; nenhum pacote
  instalado é afetado). Aconteceu neste robô em 2026-10-07.
- **`apt update` reclama de chave GPG do ROS** — baixe de novo a chave (comando `curl` do
  passo 2, seção do robô restaurado).
- **Câmera não abre / "device busy"** — só um processo pode usar a D435i por vez:
  `fuser -v /dev/video*` mostra quem está com ela.

## Referências

- Documentação oficial do G1: [FAQ (imagem de fábrica do PC2, Wi-Fi)](https://support.unitree.com/home/en/G1_developer/FAQ) ·
  [ROS2 Communication Routine](https://support.unitree.com/home/en/G1_developer/ros2_communication_routine) ·
  [About G1 (PC1/PC2)](https://support.unitree.com/home/en/G1_developer/about_G1)
- [Instalação do ROS2 Foxy (Debian)](https://docs.ros.org/en/foxy/Installation/Ubuntu-Install-Debians.html)
- [unitree_ros2](https://github.com/unitreerobotics/unitree_ros2) · [unitree_sdk2_python](https://github.com/unitreerobotics/unitree_sdk2_python)
- [Jetson Zoo — wheels do ONNX Runtime por JetPack](https://elinux.org/Jetson_Zoo#ONNX_Runtime) ·
  [TensorRT Execution Provider](https://onnxruntime.ai/docs/execution-providers/TensorRT-ExecutionProvider.html)
- [realsense-ros](https://github.com/IntelRealSense/realsense-ros) · [NoMachine](https://www.nomachine.com/download)
