# Instalação no robô (Jetson Orin NX do Unitree G1 EDU) — guia

Passo a passo para rodar o `face_recognition_ros` no computador de desenvolvimento do robô
(**PC2**), com a GPU da Jetson. Decisões e motivos: spec
[`2026-09-18-jetson-gpu-migration-design.md`](../superpowers/specs/2026-09-18-jetson-gpu-migration-design.md).

**Estado deste guia (2026-10-09):** instalado e funcionando no robô do IME — reconhecimento em
GPU (TensorRT) com uma **webcam USB presa no alto da cabeça do robô**, ~42 ms por frame
(`buffalo_l`, 640x480). A D435i do robô continua suportada como alternativa, mas olha para o
chão (ver "Câmera"). Os comandos de Python/ROS também foram verificados num container x86 com o
mesmo Ubuntu 20.04 / Python 3.8 / ROS2 Foxy (`docker/ros2.Dockerfile`).

## Estado do robô (inspeção de 2026-10-07, atualizada em 2026-10-09)

| | |
|---|---|
| Acesso | SSH `unitree@192.168.123.164` pelo cabo, ou pelo IP do Wi-Fi (senha padrão `123`, também a do `sudo`); hostname `ubuntu` |
| Sistema | JetPack 5.1.1 (`R35 REVISION: 3.1`), Ubuntu 20.04.6, kernel 5.10.104-tegra, Python 3.8.10 |
| GPU | CUDA (`/usr/local/cuda`) e TensorRT 8.5.2 instalados |
| Recursos | 15 GB de RAM (12 livres em repouso), disco de 1,9 TB (3% usado) |
| Câmeras | D435i na USB (`8086:0b3a`, fixa na cabeça, inclinada para baixo) + webcam USB nossa (`2bc5:0529`, "webcamproduct") |
| Rede | `eth0` = 192.168.123.164 (conexão `unitree1`, rede interna do robô); `wlan0` = Wi-Fi (também é um dispositivo USB) |
| ROS | **Foxy e Noetic** em `/opt/ros` (instalador comunitário fishros); repositório apt do ROS configurado |
| Python global | `numpy 1.24.4`, `opencv-python 4.13`, `torch 2.4.1`, `unitree_sdk2py 1.0.1`, `cyclonedds 0.10.2`, `pyrealsense2 2.55.1` |
| Outros | Docker 24; desktop Ubuntu (GNOME) com NoMachine 8.9.1 na porta 4000 |

### Outros projetos neste robô — regras de convivência

O robô é compartilhado. Nada do que é nosso fica fora de `~/ipe-2-code`.

- **`~/hhhh` (voz e movimentos militares).** O `unitree-start-joystick.service` sobe no boot,
  conversa com o robô por DDS na `eth0` e espera o botão **START** do controle, que dispara
  `~/hhhh/iniciar_robo.sh` (caixa Bluetooth, Piper/Whisper, `assistente.py` e
  `movimentos_militares.py` — sentido, descansar, apresentação e **continência (`F1 + B`)**, com
  poses em `~/hhhh/poses/`). Não usa câmera. O `start_joystick.py` ocupa ~80% de um núcleo o tempo
  todo.
- **Transmissão da D435i por Wi-Fi (pasta `~/cesar`, criada em 2026-07/08).** Dois serviços que
  sobem no boot: `realsense-camera.service` (D435i com a librealsense 2.58 de `/usr/local` +
  imagem comprimida, DDS no `wlan0`) e `realsense-mjpeg-bridge.service` (MJPEG por HTTP). O
  segundo declara `Requires=` do primeiro, então **desativar só o `realsense-camera` não basta**:
  o bridge o religa no boot. Eles ocupam a D435i (ver "Problemas comuns"); com a webcam USB não
  nos atrapalham.
- **Não desative, edite nem apague serviços de outros projetos** sem falar com quem os mantém.
  Para liberar a D435i só nesta sessão, `stop` (volta no próximo boot).
- **Nunca rode `pip install` fora do nosso venv** (nem com `sudo`): os outros projetos usam o
  Python global, e trocar o numpy/OpenCV de lá pode quebrá-los.
- **Não carregue o `~/ros2_ws/install/setup.bash`:** é o workspace do projeto da D435i, com um
  `realsense-ros` compilado do fonte que passaria por cima do nosso.
- **Fase 2:** a continência já existe; o reconhecimento vai precisar *dispará-la*, combinado com
  o autor — dois programas comandando o braço ao mesmo tempo é perigoso.

### O prompt do fishros e o ambiente obrigatório

A cada login, o terminal pergunta `ros:foxy(1) noetic(2) ?`. **Responda sempre `1`.** A opção 1
carrega o Foxy **e** o ambiente de DDS do robô, de que todo processo ROS2 aqui precisa:

```bash
source /opt/ros/foxy/setup.bash
source ~/cyclonedds_ws/install/setup.bash        # CycloneDDS 0.10 (o 0.7 do Foxy não lê o XML do robô)
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=$HOME/cyclonedds_ws/cyclonedds.xml    # DDS na eth0
export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH
```

Sem isso, o ROS2 cai no Fast-DDS e qualquer nó morre com `std::bad_alloc` ou é morto por falta de
memória. O `scripts/robo_tmux.sh` aplica esse ambiente sozinho. Não altere o `~/.bashrc`: alguém
pode usar o Noetic.

## 0. Acesso ao robô

**SSH pelo cabo:** ligue seu computador na rede do robô (IP fixo na faixa `192.168.123.x`, ex.:
`.170`) e `ssh unitree@192.168.123.164`. Deixe o cabo como acesso de emergência.

**Wi-Fi (para dispensar o cabo)** — rodado no PC2 ainda pelo cabo:

```bash
nmcli -f SSID,SECURITY,SIGNAL device wifi list
sudo nmcli device wifi connect "NOME_DA_REDE" password "SENHA"
ip -br addr show wlan0          # o IP que o robô pegou; use-o no ssh
```

- A conexão fica salva e volta sozinha no boot; o IP pode mudar (veja a lista de aparelhos do
  roteador/hotspot, o robô aparece como `ubuntu`).
- **Use uma rede WPA2.** Com WPA3 (comum em hotspot de celular novo) o Ubuntu 20.04 responde
  `Secrets were required, but not provided`. No Android: segurança "WPA2-Personal"; no iPhone:
  "Maximizar Compatibilidade".
- Redes de campus costumam isolar os aparelhos ou exigir login institucional; use um hotspot de
  celular ou um roteador próprio (WPA2, 2,4 GHz). O notebook tem de estar na mesma rede.
- Não mexa na conexão da `eth0`: é por ela que o PC2 fala com o computador de controle do robô.
- Quando o robô ganha Wi-Fi, os serviços da D435i do outro projeto passam a funcionar (sem Wi-Fi
  eles falham ao iniciar) — ver "Problemas comuns".

**Ver a câmera ao vivo:** pelo SSH com janelas gráficas (o `sshd` do robô já permite):

```bash
ssh -Y unitree@IP_DO_ROBO           # depois responda 1 no fishros
ros2 run rqt_image_view rqt_image_view /camera/color/image_raw
```

Fora do tmux (dentro dele não há `DISPLAY`). Pelo Wi-Fi a imagem chega atrasada; o
reconhecimento não é afetado, ele roda no robô.

**NoMachine (área de trabalho remota):** porta `4000`. Sem monitor no robô ele tenta se conectar
à tela de login (GDM) e falha; para usar, `sudo systemctl stop gdm3 && sudo /usr/NX/bin/nxserver --restart`
e escolha "criar uma área de trabalho virtual". O `ssh -Y` costuma bastar.

## 1. Conferir o sistema

```bash
cat /etc/nv_tegra_release         # esperado: R35 (release), REVISION: 3.1 = JetPack 5.1.1
python3 -V                        # esperado: 3.8.x
ls /opt/ros                       # neste robô: foxy noetic
lsusb                             # a webcam (e a D435i, 8086:0b3a)
ls /dev/v4l/by-id/                # caminho estável da webcam: ...-video-index0
```

## 2. Instalar o que falta

```bash
sudo apt update
sudo apt install -y ros-foxy-vision-msgs ros-foxy-v4l2-camera ros-foxy-rqt-image-view \
  ros-foxy-realsense2-camera ros-foxy-librealsense2 python3-venv
```

(`realsense2-camera`/`librealsense2` só para a opção D435i.) Não rode `sudo apt upgrade` no
sistema todo: ele atualizaria também os pacotes da NVIDIA (`nvidia-l4t-*`) que formam a base
validada pela Unitree.

**Sem internet no robô:** compartilhe a do notebook pelo cabo (no notebook:
`sudo sysctl -w net.ipv4.ip_forward=1` e `sudo iptables -t nat -A POSTROUTING -s 192.168.123.0/24 -o <interface_wifi_do_notebook> -j MASQUERADE`;
no robô: `sudo ip route add default via <IP_do_notebook_no_cabo>` e `sudo resolvectl dns eth0 8.8.8.8`).
Desfaça ao terminar (`-D` no lugar de `-A`; `sudo ip route del default via ...`).

**Robô restaurado de fábrica (sem `/opt/ros`):** a imagem oficial não traz ROS. Instale o Foxy
pelo procedimento oficial e depois os pacotes acima:

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

Nesse caso também falta o `~/cyclonedds_ws` (CycloneDDS 0.10 do `unitree_ros2`): siga o README
do [unitree_ros2](https://github.com/unitreerobotics/unitree_ros2).

## 3. Baixar o código

```bash
git clone https://github.com/Kalile24/ipe-2-code.git ~/ipe-2-code
cd ~/ipe-2-code
```

## 4. Ambiente Python (venv)

O venv fica dentro do repositório (`.venv`, já no `.gitignore`).

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

O OpenCV 4.10 do venv tem prioridade sobre o 4.13 global; ele é necessário porque, sem a versão
fixa, o `insightface` puxa o OpenCV 5, que quebra o `cv_bridge`. O nome do arquivo `.whl`
importa: o pip recusa a wheel se o nome não tiver `cp38-cp38-linux_aarch64`.

Conferir:

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

Fotos de cadastro: uma pasta por pessoa em `data/known_faces/<nome>/`. Em 2026-10-09 o banco
do robô tinha **uma foto por pessoa**, e a nota variou muito com o ângulo: entre 0.27 e 0.44
(abaixo do limiar de 0.45) com o rosto visto de cima pela D435i, 0.62 de frente. **Cadastre 3 a 5
fotos por pessoa, incluindo algumas tiradas pela própria câmera que vai reconhecer.**

**Cadastre no notebook e copie só o banco.** As fotos ficam no notebook (`data/known_faces/` é
ignorado pelo git e não está no robô), e o enroll **refaz o banco a partir da pasta inteira**:
rodá-lo no robô apagaria quem não tem foto lá. Os embeddings dependem só do modelo, não da
máquina.

```bash
# no notebook, na raiz do repositório
mkdir -p data/known_faces/<nome> && cp <foto>.jpg data/known_faces/<nome>/
for m in buffalo_l buffalo_sc; do .venv/bin/python -m apps.enroll --model $m; done
scp data/identity_db_buffalo_l.* data/identity_db_buffalo_sc.* unitree@IP_DO_ROBO:ipe-2-code/data/
```

O nó só lê o banco ao subir: reinicie-o depois (janela 0 do tmux, `Ctrl+C` e seta para cima).

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
deve mostrar `#!/home/unitree/ipe-2-code/.venv/bin/python3`. Depois de um `git pull` que mude
o `launch/` ou o `setup.py`, compile de novo.

## 7. Rodar

### Câmera

A **webcam USB na cabeça** é a câmera padrão. A D435i do G1 é fixa no tronco/cabeça com
inclinação de 47,6° para baixo (junta `d435_joint` do URDF) e campo vertical de 42°: a borda de
cima da imagem fica 26,6° abaixo do horizonte, então ela só vê o rosto de quem está agachado a
~1 m. Não há ajuste mecânico previsto, e mudar o suporte afeta o equipamento e os outros
usuários.

### Um comando (recomendado)

```bash
~/ipe-2-code/scripts/robo_tmux.sh            # webcam USB (padrão); "realsense" para a D435i
tmux attach -t face
```

Abre a sessão tmux `face`, já com o ambiente obrigatório e sem o prompt do fishros:

- **janela 0 `reconhecimento`** — um único `ros2 launch` que sobe a webcam (`v4l2_camera`,
  640x480, achada pelo caminho estável `/dev/v4l/by-id/...-video-index0`) **e** o nó de
  reconhecimento;
- **janela 1 `deteccoes`** — `watch_detections.py`, que imprime `nome: nota` por rosto (ou
  `(nenhum rosto)`) a cada frame;
- **janela 2 `camera`** — só no modo `realsense`.

`Ctrl+b` e o número troca de janela; `Ctrl+b` e `d` sai deixando tudo rodando;
`tmux kill-session -t face` encerra tudo. `VIDEO=/dev/videoN robo_tmux.sh` força outro dispositivo.

### Sem o script

Com o ambiente obrigatório e os `source` do passo 6, num terminal:

```bash
ros2 launch face_recognition_ros face_recognition.launch.py camera:=v4l2 \
  video_device:=/dev/v4l/by-id/usb-webcamvendor_webcamproduct_00000000-video-index0 \
  onnx_providers:=TensorrtExecutionProvider,CUDAExecutionProvider,CPUExecutionProvider
```

e noutro `python3 ~/ipe-2-code/scripts/watch_detections.py`. Para a D435i: um terminal com
`ros2 launch realsense2_camera rs_launch.py` (publica em `/camera/color/image_raw`) e o launch
acima com `camera:=none`. Para comparar modelos: `model_name:=buffalo_sc` (o banco desse modelo
precisa existir).

### O que o log tem que mostrar

1. `providers ativos: {...}` com `TensorrtExecutionProvider`. Se aparecer
   `providers pedidos mas NÃO ativos`, a GPU não está em uso (ver "Problemas comuns").
2. **Na primeira execução** o TensorRT monta os engines otimizados: o nó fica ~2 min sem
   processar (um de cada modelo; o de reconhecimento só quando aparece o primeiro rosto). Os
   engines ficam em `~/.insightface/trt_cache/<modelo>/` e as execuções seguintes começam na hora.
   Apagar essa pasta força montar de novo (necessário se mudar a versão do TensorRT).
3. **Sinal de vida a cada 10 s:** `N imagens processadas em 10 s (X/s), M rostos`. Com a webcam,
   ~20/s. Se aparecer `nenhuma imagem em 10 s`, a câmera parou ou o tópico está errado; se nem
   essa linha aparecer, o nó está preso dentro de um frame.

### Observar por fora

```bash
ros2 topic hz /camera/color/image_raw            # a câmera está publicando? (~30/s)
ros2 topic info /camera/color/image_raw          # 1 publisher + o nosso nó como subscriber
ros2 topic echo /camera/color/image_raw --no-arr # cabeçalho das imagens, sem os pixels
journalctl -k --since "-10min" | grep -i "usb 1-2"   # a webcam reconectou?
```

Num pipe (`| grep`, `| tail`), o `ros2 topic hz` não imprime nada até terminar — use
`PYTHONUNBUFFERED=1` ou rode sem pipe.

## 8. Falar com o robô (Fase 2)

O ambiente obrigatório (prompt do fishros) já põe o CycloneDDS na `eth0`, a interface da rede
do robô — a mesma que o serviço do joystick usa e a que o `unitree_ros2` oficial indica. O
`~/cyclonedds_ws/cyclonedds.xml` é o XML com `<NetworkInterface name="eth0" .../>`.

## Checklist

Confirmado no robô (2026-10-07 a 09): JetPack 5.1.1 / Python 3.8; CUDA e TensorRT; ROS2 Foxy;
pacotes do passo 2; providers GPU no venv e `cv2.CV_8UC3 == 16`; shebang do nó no venv; log com
`TensorrtExecutionProvider` ativo; ~42 ms por frame com `buffalo_l` em 640x480 (TensorRT), ~24/s;
reconhecimento de uma pessoa cadastrada (`marcos: 0.62`); acesso por Wi-Fi.

Falta:

1. Latência em CPU (`onnx_providers:=CPUExecutionProvider`) e com `buffalo_sc`, para comparar.
2. Memória livre com tudo rodando (`free -h`, `tegrastats`).
3. Teste longo (30 min+) com o sinal de vida, para ver se o nó para de receber imagens (ver
   "Problemas comuns").
4. Distância máxima de reconhecimento com a webcam na cabeça.
5. Cadastro com 3 a 5 fotos por pessoa (hoje: uma) e nova medição das notas.

## Problemas comuns

- **Nó não acha `insightface`/`onnxruntime` (`ModuleNotFoundError`)** — o pacote foi
  compilado com `colcon` puro. Refaça o passo 6 com `python3 -m colcon build`, com o venv ativo.
- **`std::bad_alloc` ou processo morto (código 137) ao rodar qualquer nó** — o terminal está sem
  o ambiente obrigatório (respondeu `2` ou nada no fishros). Abra outro terminal e responda `1`.
- **Watcher sem saída / reconhecimento "parou"** — olhe o sinal de vida da janela 0. Se o nó diz
  `nenhuma imagem em 10 s`, confira a câmera com `ros2 topic hz`. Já aconteceu de o nó parar de
  receber imagens com a câmera publicando normalmente (para outros assinantes); sem causa
  encontrada. Reinicie o nó (`Ctrl+C` na janela 0 e seta para cima). Para investigar,
  `~/ipe-2-code/.venv/bin/pip install py-spy` e
  `sudo ~/ipe-2-code/.venv/bin/py-spy dump --pid $(pgrep -f lib/face_recognition_ros/face_recognition_node)`
  mostra em que linha ele está.
- **Webcam desconecta sozinha** — o kernel registra `usb 1-2...: New USB device` de novo e o
  `/dev/videoN` muda de número; o nó da câmera fica preso ao dispositivo antigo e para de
  publicar (às vezes nem responde ao `Ctrl+C`: `pkill -f v4l2_camera_node`). Causa física:
  prenda o cabo sem tensão, troque de porta ou use um hub USB com fonte própria. Depois, reabra
  (o caminho `/dev/v4l/by-id/` acha a webcam no número novo).
- **`Device or resource busy` / `Failed mapping device memory` na webcam** — já há outro
  processo com ela aberta (por exemplo, a janela 0 do tmux): só um por vez.
  `pgrep -af v4l2_camera_node`.
- **D435i: `No RealSense devices were found!`** — o serviço de outro projeto pegou a câmera: a
  librealsense dele fala com o USB direto e desliga o driver de vídeo padrão (somem os
  `/dev/video*` da D435i), e ao terminar não religa. Para usar a D435i nesta sessão:
  ```bash
  sudo systemctl stop realsense-mjpeg-bridge.service realsense-camera.service
  for i in 0 1 2 3 4; do echo 2-3:1.$i | sudo tee /sys/bus/usb/drivers/uvcvideo/bind; done
  ```
  (`No such device` em alguns é normal: o driver pega as interfaces em pares.) **Não** faça
  `unbind` do dispositivo inteiro (`/sys/bus/usb/drivers/usb/unbind`) nem `kill -9` na câmera:
  a D435i trava (`error -71`, some do `lsusb`) e só volta desligando o robô da bateria — um
  `reboot` não corta a energia dela.
- **`KeyError: 16` ao converter frame** — o OpenCV 5 entrou no venv (o OpenCV 5 mudou o código
  `CV_8UC3` de 16 para 64 e o `cv_bridge` espera 16). Corrija com
  `pip install --no-deps "opencv-python-headless==4.10.0.84"` e remova outros `opencv-*` do venv.
- **`providers ativos` só com CPU** — confira `pip list | grep -i onnxruntime`: deve haver só
  `onnxruntime-gpu 1.16.0`. Se aparecer `onnxruntime` (CPU), desinstale os dois e reinstale a
  wheel GPU.
- **`AttributeError: _ARRAY_API not found`** — entrou numpy 2: `pip install "numpy==1.24.4"`.
- **`could not connect to display` no `rqt_image_view`** — conexão sem `-Y`, ou dentro do tmux.
- **`Unable to locate package ros-foxy-...` mesmo depois do `apt update`** — a lista do
  repositório do ROS em cache ficou vazia (de um `apt update` sem internet) e, como o Foxy não
  muda mais, o apt não baixa de novo: `sudo rm -rf /var/lib/apt/lists/* && sudo apt update`.
- **`No matching distribution found` no pip** — pip antigo: `pip install --upgrade pip`.

## Referências

- Documentação oficial do G1: [FAQ (imagem de fábrica do PC2, Wi-Fi)](https://support.unitree.com/home/en/G1_developer/FAQ) ·
  [ROS2 Communication Routine](https://support.unitree.com/home/en/G1_developer/ros2_communication_routine) ·
  [About G1 (PC1/PC2)](https://support.unitree.com/home/en/G1_developer/about_G1)
- [Instalação do ROS2 Foxy (Debian)](https://docs.ros.org/en/foxy/Installation/Ubuntu-Install-Debians.html)
- [unitree_ros2](https://github.com/unitreerobotics/unitree_ros2) · [unitree_sdk2_python](https://github.com/unitreerobotics/unitree_sdk2_python)
- [Jetson Zoo — wheels do ONNX Runtime por JetPack](https://elinux.org/Jetson_Zoo#ONNX_Runtime) ·
  [TensorRT Execution Provider](https://onnxruntime.ai/docs/execution-providers/TensorRT-ExecutionProvider.html)
- [v4l2_camera](https://gitlab.com/boldhearts/ros2_v4l2_camera) · [realsense-ros](https://github.com/IntelRealSense/realsense-ros)
