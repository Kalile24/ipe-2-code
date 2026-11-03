#!/usr/bin/env bash
# Servidor de voz (Piper, pt_BR-faber-medium) da rotina de cumprimento, sem depender do ~/hhhh.
# Uso, no robô: ~/ipe-2-code/scripts/robo_voz.sh        (o robo_rotina_cumprimento.sh já chama)
#
# POST http://127.0.0.1:5005/synthesize {"text": ...} gera a fala e a toca com paplay na saída
# padrão do PulseAudio (a caixa Bluetooth); só responde depois de tocar.
#
# Usa a imagem Docker que já está no robô (openvoice-piper-whisper-jetson:1.0, com o Piper e a
# voz em /opt/piper), num contêiner nosso (ipe-piper) que só sobe o Piper: não monta nada do
# ~/hhhh nem sobe o Whisper. Se algo já responde na porta 5005 (por exemplo o contêiner
# openvoice-piper do START do ~/hhhh), ele é reaproveitado: a API é a mesma.
# Parar: docker stop ipe-piper
set -euo pipefail

CONTAINER=ipe-piper
IMAGE=${PIPER_IMAGE:-openvoice-piper-whisper-jetson:1.0}
PULSE_DIR=/run/user/$(id -u)/pulse
PULSE_COOKIE=$HOME/.config/pulse/cookie
HEALTH=http://127.0.0.1:5005/health

pronto() { curl -fsS "$HEALTH" >/dev/null 2>&1; }

if pronto; then
    echo "Piper já responde em $HEALTH."
    exit 0
fi
[ -S "$PULSE_DIR/native" ] || { echo "ERRO: PulseAudio sem socket em $PULSE_DIR/native (sessão gráfica do unitree aberta?)"; exit 1; }
[ -f "$PULSE_COOKIE" ] || { echo "ERRO: cookie do PulseAudio não encontrado: $PULSE_COOKIE"; exit 1; }
docker image inspect "$IMAGE" >/dev/null 2>&1 || { echo "ERRO: imagem $IMAGE não está no robô (docker images)"; exit 1; }

if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    docker start "$CONTAINER" >/dev/null
else
    docker run -d --name "$CONTAINER" --runtime nvidia --network host --device /dev/snd \
        --env PULSE_SERVER="unix:$PULSE_DIR/native" --env PULSE_COOKIE=/tmp/pulse-cookie \
        --volume "$PULSE_DIR:$PULSE_DIR" --volume "$PULSE_COOKIE:/tmp/pulse-cookie:ro" \
        "$IMAGE" /bin/bash -lc 'PYTHONPATH=/opt/OpenVoice exec /usr/bin/python3 /opt/piper/piper_server.py' >/dev/null
fi

for _ in $(seq 1 60); do
    pronto && { echo "Piper pronto em $HEALTH (contêiner $CONTAINER)."; exit 0; }
    sleep 1
done
echo "ERRO: Piper não respondeu em 60 s (docker logs $CONTAINER)"
exit 1
