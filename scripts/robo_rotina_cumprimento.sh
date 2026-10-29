#!/usr/bin/env bash
# Rotina de cumprimento: o robô reconhece quem está no config/reactions.yaml e executa os passos
# (posturas militares do ~/hhhh + fala pela caixa Bluetooth). Roda à mão, no robô:
#   ~/ipe-2-code/scripts/robo_rotina_cumprimento.sh [--armado] [usb|realsense]
#   sem --armado: fala de verdade, posturas só no log (teste seguro).
#   --armado: o robô vai para damp, levanta e fica em equilíbrio (como o F1+UP) — NO SUPORTE.
# Depois: tmux attach -t rotina. Ctrl+C na janela "rotina" devolve os braços e encerra.
# Armado, a janela "emergencia" fica pronta: Enter = damp na hora (scripts/robo_emergencia.py).
# Cumprimentar de novo antes dos 5 min: scripts/robo_liberar_cumprimento.sh [nome]
set -e
REPO=$(cd "$(dirname "$0")/.." && pwd)
SESSAO=rotina
HHHH=$HOME/hhhh
CAIXA=A8:AA:CD:C6:5C:A3  # caixa Bluetooth KD-833 (a mesma do ~/hhhh/iniciar_robo.sh)
ARMADO=false
CAMERA=usb
for arg in "$@"; do
    case "$arg" in
        --armado) ARMADO=true ;;
        usb|realsense) CAMERA=$arg ;;
        *) echo "Argumento desconhecido: $arg (use --armado e/ou usb|realsense)"; exit 1 ;;
    esac
done
VIDEO=${VIDEO:-$(ls /dev/v4l/by-id/*-video-index0 2>/dev/null | head -1)}
case "$CAMERA" in
    usb) ARGS_CAMERA="camera:=v4l2 video_device:=${VIDEO:-/dev/video0}" ;;
    realsense) ARGS_CAMERA="camera:=none" ;;
esac

if tmux has-session -t "$SESSAO" 2>/dev/null; then
    echo "A sessão '$SESSAO' já existe: entre com 'tmux attach -t $SESSAO' ou feche com 'tmux kill-session -t $SESSAO'."
    exit 1
fi
# Dois donos do braço (ou da caixa) ao mesmo tempo: os serviços do START do ~/hhhh não podem estar de pé.
for proc in movimentos_militares.py assistente.py; do
    if pgrep -f "$HHHH/$proc" >/dev/null; then
        echo "ERRO: $proc (~/hhhh) está rodando — alguém apertou START no controle."
        echo "      Ele disputaria o braço/a caixa com a rotina. Encerre-o antes (ou reinicie o robô)."
        exit 1
    fi
done

echo "[1/3] Caixa Bluetooth..."
if ! bluetoothctl info "$CAIXA" | grep -q "Connected: yes"; then
    for _ in 1 2 3 4 5; do
        bluetoothctl connect "$CAIXA" >/dev/null 2>&1 || true
        sleep 2
        bluetoothctl info "$CAIXA" | grep -q "Connected: yes" && break
    done
fi
bluetoothctl info "$CAIXA" | grep -q "Connected: yes" || { echo "ERRO: caixa Bluetooth não conectou (está ligada?)"; exit 1; }
SINK=""
for _ in $(seq 1 20); do
    SINK=$(pactl list short sinks | awk '/A8_AA_CD_C6_5C_A3/ {print $2; exit}')
    [ -n "$SINK" ] && break
    sleep 1
done
[ -n "$SINK" ] || { echo "ERRO: caixa conectada, mas o PulseAudio não criou a saída dela"; exit 1; }
pactl set-default-sink "$SINK"

echo "[2/3] Servidor de voz (Piper)..."
"$HHHH/start_tts_stt.sh" >/dev/null
for i in $(seq 1 60); do
    curl -fsS http://127.0.0.1:5005/health >/dev/null 2>&1 && break
    [ "$i" = 60 ] && { echo "ERRO: Piper não respondeu em 60 s (docker logs openvoice-piper)"; exit 1; }
    sleep 1
done

if [ "$ARMADO" = true ]; then
    echo
    echo "ARMADO: o robô vai para damp (motores soltos), levanta e fica em equilíbrio."
    read -r -p "O robô está preso no suporte e com espaço livre em volta? [s/N] " resposta
    [ "$resposta" = s ] || [ "$resposta" = S ] || { echo "Cancelado."; exit 1; }
fi

echo "[3/3] Reconhecimento + reação + corpo (sessão tmux '$SESSAO')..."
AMBIENTE="source $REPO/scripts/ambiente_robo.sh"
rodar() { tmux send-keys -t "$SESSAO:$1" "$AMBIENTE" C-m "$2" C-m; }
tmux new-session -d -s "$SESSAO" -n rotina "bash --norc"
tmux new-window -t "$SESSAO:" -n status "bash --norc"
tmux new-window -t "$SESSAO:" -n deteccoes "bash --norc"
if [ "$ARMADO" = true ]; then
    # Parada de emergência já conectada: Enter nesta janela = damp na hora.
    tmux new-window -t "$SESSAO:" -n emergencia "bash --norc"
    tmux send-keys -t "$SESSAO:emergencia" "$REPO/.venv/bin/python $REPO/scripts/robo_emergencia.py" C-m
fi
if [ "$CAMERA" = realsense ]; then
    tmux new-window -t "$SESSAO:" -n camera "bash --norc"
    rodar camera "ros2 launch realsense2_camera rs_launch.py"
fi
rodar rotina "ros2 launch robot_reaction_ros rotina.launch.py armed:=$ARMADO $ARGS_CAMERA \
onnx_providers:=TensorrtExecutionProvider,CUDAExecutionProvider,CPUExecutionProvider"
rodar status "ros2 topic echo /reaction/rotina_status"
rodar deteccoes "python3 $REPO/scripts/watch_detections.py"
tmux select-window -t "$SESSAO:rotina"

echo
echo "Pronto ($([ "$ARMADO" = true ] && echo ARMADO || echo desarmado: só fala)). Entre com: tmux attach -t $SESSAO"
echo "  Ctrl+b e 0/1/2 troca de janela; Ctrl+C na janela 'rotina' devolve os braços e encerra."
echo "  Cumprimentar de novo: $REPO/scripts/robo_liberar_cumprimento.sh [nome]"
[ "$ARMADO" = true ] && echo "  EMERGÊNCIA: Enter na janela 'emergencia' (ou robo_emergencia.py --agora) = damp na hora."
