#!/usr/bin/env bash
# Wi-Fi próprio do robô (ponto de acesso no wlan0) para abrir o painel: http://10.42.0.1:8080
#   ~/ipe-2-code/scripts/robo_hotspot.sh liga      # rede IPE-G1 (senha em HOTSPOT_SENHA, padrão abaixo)
#   ~/ipe-2-code/scripts/robo_hotspot.sh desliga   # volta para a rede Wi-Fi de antes
#   ~/ipe-2-code/scripts/robo_hotspot.sh estado
#   ~/ipe-2-code/scripts/robo_hotspot.sh boot-liga      # sobe sozinho a cada boot (ligado em 2026-11-05)
#   ~/ipe-2-code/scripts/robo_hotspot.sh boot-desliga   # volta a entrar nas redes Wi-Fi salvas no boot
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
        # 2,4 GHz canal 1 e sem PMF: com a faixa automática o celular não entrava (senha recusada) no
        # adaptador Realtek do robô; assim entrou (2026-11-05), como a antiga rede ipe2-ap.
        # powersave 2 = desligado: ligado, a latência até o celular ia de 3 a 194 ms (painel lento).
        sudo nmcli connection modify "$CONEXAO" 802-11-wireless.band bg 802-11-wireless.channel 1 802-11-wireless-security.pmf 1 \
            802-11-wireless.powersave 2
        sudo nmcli connection up "$CONEXAO"
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
    boot-liga)  # o hotspot sobe sozinho no boot (prioridade acima das outras redes salvas)
        sudo nmcli connection modify "$CONEXAO" connection.autoconnect yes connection.autoconnect-priority 100
        echo "Hotspot $SSID vai subir sozinho no boot (desfaça com: $0 boot-desliga)"
        ;;
    boot-desliga)  # no boot o robô volta a entrar nas redes Wi-Fi salvas
        sudo nmcli connection modify "$CONEXAO" connection.autoconnect no
        echo "Hotspot não sobe mais no boot"
        ;;
    estado)
        nmcli -f GENERAL.CONNECTION,IP4.ADDRESS device show wlan0
        nmcli -g connection.autoconnect connection show "$CONEXAO" 2>/dev/null | sed 's/^/sobe no boot: /'
        ;;
    *) echo "Uso: $0 liga|desliga|boot-liga|boot-desliga|estado"; exit 1 ;;
esac
