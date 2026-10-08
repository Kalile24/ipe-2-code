#!/usr/bin/env bash
# Abre no robô a sessão tmux "face" com as três janelas do passo 7 do guia da Jetson:
# câmera, reconhecimento e detecções — já com o ambiente ROS2 Foxy + CycloneDDS + venv.
# Uso: ~/ipe-2-code/scripts/robo_tmux.sh [realsense|usb] [image_topic]   e depois: tmux attach -t face
#   realsense (padrão): D435i do robô.  usb: webcam USB extra (VIDEO=/dev/videoN troca o dispositivo).
# Janelas sem ~/.bashrc (bash --norc), para não cair no prompt do fishros.
set -e
REPO=$(cd "$(dirname "$0")/.." && pwd)
SESSAO=face
CAMERA=${1:-realsense}
TOPICO=${2:-/camera/color/image_raw}
VIDEO=${VIDEO:-$(ls /dev/v4l/by-id/*-video-index0 2>/dev/null | head -1)}
case "$CAMERA" in
    realsense) CMD_CAMERA="ros2 launch realsense2_camera rs_launch.py" ;;
    usb) CMD_CAMERA="ros2 run v4l2_camera v4l2_camera_node --ros-args -p video_device:=${VIDEO:-/dev/video0} \
-p \"image_size:=[640,480]\" -r image_raw:=$TOPICO" ;;
    *) echo "Câmera desconhecida: $CAMERA (use realsense ou usb)"; exit 1 ;;
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
    echo "       Pare com 'sudo systemctl stop realsense-camera.service'."
fi

tmux new-session -d -s "$SESSAO" -n camera "bash --norc"
tmux new-window -t "$SESSAO" -n reconhecimento "bash --norc"
tmux new-window -t "$SESSAO" -n deteccoes "bash --norc"

rodar() { tmux send-keys -t "$SESSAO:$1" "$AMBIENTE" C-m "$2" C-m; }
rodar camera "$CMD_CAMERA"
rodar reconhecimento "sleep 5; ros2 launch face_recognition_ros face_recognition.launch.py camera:=none \
image_topic:=$TOPICO onnx_providers:=TensorrtExecutionProvider,CUDAExecutionProvider,CPUExecutionProvider"
rodar deteccoes "python3 $REPO/scripts/watch_detections.py"

echo "Sessão '$SESSAO' aberta. Entre com: tmux attach -t $SESSAO   (Ctrl+b e 0/1/2 troca de janela)"
