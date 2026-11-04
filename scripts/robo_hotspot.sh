#!/usr/bin/env bash
# Wi-Fi próprio do robô (ponto de acesso no wlan0) para abrir o painel: http://10.42.0.1:8080
#   ~/ipe-2-code/scripts/robo_hotspot.sh liga      # rede IPE-G1 (senha em HOTSPOT_SENHA, padrão abaixo)
#   ~/ipe-2-code/scripts/robo_hotspot.sh desliga   # volta para a rede Wi-Fi de antes
#   ~/ipe-2-code/scripts/robo_hotspot.sh estado
# ATENÇÃO: com o hotspot ligado o robô SAI da rede Wi-Fi em que estava e a transmissão da D435i do
# projeto ~/cesar (wlan0) para. Combine com eles antes. O cabo (192.168.123.164) continua valendo.
set -e
SSID=${HOTSPOT_SSID:-IPE-G1}
SENHA=${HOTSPOT_SENHA:-ipe-g1-2026}
CONEXAO=ipe-hotspot
ANTERIOR=$HOME/.ipe-wifi-anterior  # nome da conexão Wi-Fi que estava ativa
case "${1:-}" in
    liga)
        [ ${#SENHA} -ge 8 ] || { echo "A senha precisa de 8 caracteres ou mais"; exit 1; }
        nmcli -t -f NAME,DEVICE connection show --active | awk -F: '$2=="wlan0" && $1!="'$CONEXAO'" {print $1}' > "$ANTERIOR" || true
        sudo nmcli device wifi hotspot ifname wlan0 con-name "$CONEXAO" ssid "$SSID" password "$SENHA"
        echo "Hotspot $SSID ligado. Conecte-se a ele e abra http://10.42.0.1:8080"
        [ -s "$ANTERIOR" ] && echo "(antes: $(cat "$ANTERIOR"); 'desliga' volta para ela)"
        ;;
    desliga)
        sudo nmcli connection down "$CONEXAO" 2>/dev/null || true
        if [ -s "$ANTERIOR" ]; then
            sudo nmcli connection up "$(cat "$ANTERIOR")" && echo "De volta em $(cat "$ANTERIOR")"
        else
            echo "Hotspot desligado (não havia Wi-Fi anterior registrado)"
        fi
        ;;
    estado)
        nmcli -f GENERAL.CONNECTION,IP4.ADDRESS device show wlan0
        ;;
    *) echo "Uso: $0 liga|desliga|estado"; exit 1 ;;
esac
