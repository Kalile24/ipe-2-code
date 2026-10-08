#!/usr/bin/env bash
# Abre no robô a sessão tmux "face" (passo 7 do guia da Jetson), já com o ambiente
# ROS2 Foxy + CycloneDDS + venv:
#   janela 0 "reconhecimento": um único launch com câmera + reconhecimento (log com sinal de vida a cada 10 s)
#   janela 1 "deteccoes": watch_detections.py
#   janela 2 "camera": só com realsense, que roda o driver da D435i à parte
# Uso: ~/ipe-2-code/scripts/robo_tmux.sh [usb|realsense]   e depois: tmux attach -t face
#   usb (padrão): webcam USB na cabeça do robô (VIDEO=/dev/videoN troca o dispositivo).
#   realsense: D435i do robô (inclinada 47,6° para baixo: só vê quem está agachado).
# Janelas sem ~/.bashrc (bash --norc), para não cair no prompt do fishros.
set -e
REPO=$(cd "$(dirname "$0")/.." && pwd)
SESSAO=face
CAMERA=${1:-usb}
VIDEO=${VIDEO:-$(ls /dev/v4l/by-id/*-video-index0 2>/dev/null | head -1)}
case "$CAMERA" in
    usb) ARGS_CAMERA="camera:=v4l2 video_device:=${VIDEO:-/dev/video0}" ;;
    realsense) ARGS_CAMERA="camera:=none" ;;
    *) echo "Câmera desconhecida: $CAMERA (use usb ou realsense)"; exit 1 ;;
esac
AMBIENTE="source /opt/ros/foxy/setup.bash && source ~/cyclonedds_ws/install/setup.bash \
&& export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp CYCLONEDDS_URI=\$HOME/cyclonedds_ws/cyclonedds.xml \
LD_LIBRARY_PATH=/usr/local/lib:\$LD_LIBRARY_PATH \
&& source $REPO/.venv/bin/activate && source $REPO/ros2_ws/install/setup.bash"

if tmux has-session -t "$SESSAO" 2>/dev/null; then
    echo "A sessão '$SESSAO' já existe: entre com 'tmux attach -t $SESSAO' ou feche com 'tmux kill-session -t $SESSAO'."
    exit 1
fi
if [ "$CAMERA" = realsense ] && systemctl is-active --quiet realsense-camera.service; then
    echo "Aviso: o realsense-camera.service (outro projeto) está ativo e disputa a D435i."
    echo "       Pare com 'sudo systemctl stop realsense-mjpeg-bridge.service realsense-camera.service'."
fi

rodar() { tmux send-keys -t "$SESSAO:$1" "$AMBIENTE" C-m "$2" C-m; }
tmux new-session -d -s "$SESSAO" -n reconhecimento "bash --norc"
tmux new-window -t "$SESSAO" -n deteccoes "bash --norc"
if [ "$CAMERA" = realsense ]; then
    tmux new-window -t "$SESSAO" -n camera "bash --norc"
    rodar camera "ros2 launch realsense2_camera rs_launch.py"
fi
rodar reconhecimento "ros2 launch face_recognition_ros face_recognition.launch.py $ARGS_CAMERA \
onnx_providers:=TensorrtExecutionProvider,CUDAExecutionProvider,CPUExecutionProvider"
rodar deteccoes "python3 $REPO/scripts/watch_detections.py"
tmux select-window -t "$SESSAO:reconhecimento"

echo "Sessão '$SESSAO' aberta. Entre com: tmux attach -t $SESSAO   (Ctrl+b e 0/1 troca de janela)"
