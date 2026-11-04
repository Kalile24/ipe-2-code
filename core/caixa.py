"""Qual caixa Bluetooth o robô usa: a padrão, ou a salva em data/caixa.txt pelo painel."""
from __future__ import annotations

import re

CAIXA_PADRAO = "A8:AA:CD:C6:5C:A3"  # KD-833 do robô; também é o padrão do robo_rotina_cumprimento.sh
_MAC = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")


def mac_valido(mac: str) -> bool:
    return bool(_MAC.match(mac))


def caixa_atual(arquivo: str) -> str:
    """A caixa salva, ou a padrão se não há arquivo (ou ele não tem um endereço válido)."""
    try:
        with open(arquivo) as f:
            mac = f.read().strip()
    except OSError:
        return CAIXA_PADRAO
    return mac if mac_valido(mac) else CAIXA_PADRAO


def nome_do_sink(mac: str) -> str:
    """O endereço como aparece no nome da saída do PulseAudio."""
    return mac.replace(":", "_")


def ler_dispositivos(saida: str) -> list[dict[str, str]]:
    """Linhas `Device <mac> <nome>` do `bluetoothctl devices`."""
    dispositivos = []
    for linha in saida.splitlines():
        partes = linha.split(" ", 2)
        if len(partes) == 3 and partes[0] == "Device" and mac_valido(partes[1]):
            dispositivos.append({"mac": partes[1], "nome": partes[2]})
    return dispositivos
