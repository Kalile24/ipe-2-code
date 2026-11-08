#!/usr/bin/env bash
# Mede o microfone dos comandos de voz: lista os dispositivos, grava 5 s e mostra tamanho e pico.
# Não mexe no robô (nem ROS, nem movimento). Uso, no robô, falando durante os 5 s:
#   ~/ipe-2-code/scripts/robo_medir_voz.sh [dispositivo ALSA]     (padrão: default; ex.: plughw:1,0)
# O dispositivo bom é o que vai em  microfone:=<dispositivo>  no rotina.launch.py.
# O áudio vai para /dev/shm (memória) e é apagado ao sair, de qualquer jeito.
set -u
DISP=${1:-default}
command -v arecord >/dev/null || { echo "ERRO: arecord não encontrado (sudo apt install alsa-utils)."; exit 1; }
echo "Dispositivos de captura:"
arecord -l
ARQ=$(mktemp /dev/shm/medir_voz.XXXXXX.wav)
trap 'rm -f "$ARQ"' EXIT
echo
echo "Gravando 5 s de '$DISP' (16 kHz, mono, S16_LE): FALE AGORA."
arecord -D "$DISP" -f S16_LE -r 16000 -c 1 -d 5 -t wav "$ARQ" || { echo "ERRO: arecord falhou com '$DISP'."; exit 1; }
echo "Tamanho: $(stat -c %s "$ARQ") bytes (esperado ~160000)"
if command -v sox >/dev/null; then
    sox "$ARQ" -n stat 2>&1 | grep -E "Maximum amplitude|Minimum amplitude|Rough"
    echo "Pico perto de 0 = microfone mudo ou dispositivo errado; perto de 1,0 = estourando."
else
    echo "sox não instalado: pico não medido (sudo apt install sox)."
fi
