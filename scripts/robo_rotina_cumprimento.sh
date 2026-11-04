#!/usr/bin/env bash
# Rotina de cumprimento: o robô reconhece quem está no config/reactions.yaml e executa os passos
# (posturas militares + fala pela caixa Bluetooth). Também é o jeito de subir só o reconhecimento
# (desarmado, sem a caixa). Tudo vem deste repositório: o ~/hhhh não precisa existir. Roda à mão,
# no robô:
#   ~/ipe-2-code/scripts/robo_rotina_cumprimento.sh [--armado] [usb|realsense]
#   sem --armado: fala de verdade, posturas só no log (teste seguro).
#   --armado: o robô vai para damp, levanta e fica em equilíbrio (como o F1+UP) — NO SUPORTE.
#   --controle: o que o combo F2+UP do controle roda (scripts/robo_controle.py): armado, sem
#               perguntas, só com o robô já em equilíbrio (FSM 801, nunca damp → em pé), reações
#               automáticas desligadas (F2+RIGHT cumprimenta, F2+LEFT liga/desliga).
#   --estagios LISTA: virar,aproximar,fala,posturas (padrão: os do config/operacao.yaml).
#   OPERACAO=~/operacao.yaml: usa outro arquivo de operação (padrão: data/operacao.yaml, que o painel
#   salva; sem ele, o config/operacao.yaml do pacote).
# Depois: tmux attach -t rotina. Ctrl+C na janela "rotina" devolve os braços e encerra.
# Armado, a janela "emergencia" fica pronta: Enter = damp na hora (scripts/robo_emergencia.py).
# Cumprimentar de novo antes dos 5 min: scripts/robo_liberar_cumprimento.sh [nome]
set -e
REPO=$(cd "$(dirname "$0")/.." && pwd)
SESSAO=rotina
HHHH=$HOME/hhhh  # só para checar se o START do outro projeto está de pé
CAIXA=A8:AA:CD:C6:5C:A3  # caixa Bluetooth KD-833 do robô
ARMADO=false
CONTROLE=false
ESTAGIOS=""
CAMERA=usb
while [ $# -gt 0 ]; do
    case "$1" in
        --armado) ARMADO=true ;;
        --controle) ARMADO=true; CONTROLE=true ;;
        --estagios) shift; ESTAGIOS=${1:-}; [ -n "$ESTAGIOS" ] || { echo "--estagios precisa de uma lista"; exit 1; } ;;
        usb|realsense) CAMERA=$1 ;;
        *) echo "Argumento desconhecido: $1 (use --armado, --controle, --estagios LISTA e/ou usb|realsense)"; exit 1 ;;
    esac
    shift
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
# Sem a caixa a rotina roda muda (fala que falha não para o movimento): serve para testar o
# reconhecimento sozinho.
SINK=""
if bluetoothctl info "$CAIXA" | grep -q "Connected: yes"; then
    for _ in $(seq 1 20); do
        SINK=$(pactl list short sinks | awk '/A8_AA_CD_C6_5C_A3/ {print $2; exit}')
        [ -n "$SINK" ] && break
        sleep 1
    done
fi
if [ -n "$SINK" ]; then
    pactl set-default-sink "$SINK"
else
    echo "AVISO: caixa Bluetooth não conectou (está ligada?): a rotina vai rodar sem som."
fi

echo "[2/3] Servidor de voz (Piper)..."
"$REPO/scripts/robo_voz.sh"

if [ "$ARMADO" = true ] && [ "$CONTROLE" = false ]; then
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
if [ "$ARMADO" = true ] && [ "$CONTROLE" = false ]; then
    # Parada de emergência já conectada (damp: SÓ com o robô no suporte; fora dele, ele cai): Enter nesta janela = damp na hora.
    tmux new-window -t "$SESSAO:" -n emergencia "bash --norc"
    tmux send-keys -t "$SESSAO:emergencia" "$REPO/.venv/bin/python $REPO/scripts/robo_emergencia.py" C-m
fi
if [ "$CAMERA" = realsense ]; then
    tmux new-window -t "$SESSAO:" -n camera "bash --norc"
    rodar camera "ros2 launch realsense2_camera rs_launch.py"
fi
ARGS_MODO="so_equilibrio:=$CONTROLE automatico:=$([ "$CONTROLE" = true ] && echo false || echo true)"
[ -n "$ESTAGIOS" ] && ARGS_MODO="$ARGS_MODO estagios:=$ESTAGIOS"
# O painel salva em data/operacao.yaml; OPERACAO=arquivo escolhe outro; sem nenhum, o do pacote.
[ -z "${OPERACAO:-}" ] && [ -f "$REPO/data/operacao.yaml" ] && OPERACAO=$REPO/data/operacao.yaml
[ -n "${OPERACAO:-}" ] && ARGS_MODO="$ARGS_MODO operacao_file:=$OPERACAO"
rodar rotina "ros2 launch robot_reaction_ros rotina.launch.py armed:=$ARMADO $ARGS_MODO $ARGS_CAMERA \
onnx_providers:=TensorrtExecutionProvider,CUDAExecutionProvider,CPUExecutionProvider"
rodar status "ros2 topic echo /reaction/rotina_status"
rodar deteccoes "python3 $REPO/scripts/watch_detections.py"
tmux select-window -t "$SESSAO:rotina"

echo
echo "Pronto ($([ "$ARMADO" = true ] && echo ARMADO || echo desarmado: só fala)). Entre com: tmux attach -t $SESSAO"
echo "  Ctrl+b e 0/1/2 troca de janela; Ctrl+C na janela 'rotina' devolve os braços e encerra."
echo "  Cumprimentar de novo: $REPO/scripts/robo_liberar_cumprimento.sh [nome]"
if [ "$CONTROLE" = true ]; then
    echo "  Controle: F2+RIGHT cumprimenta agora, F2+LEFT liga/desliga as reações, F2+DOWN para."
elif [ "$ARMADO" = true ]; then
    echo "  EMERGÊNCIA (só no suporte: fora dele o damp derruba o robô): Enter na janela 'emergencia'"
    echo "  (ou robo_emergencia.py --agora) = damp na hora."
fi
