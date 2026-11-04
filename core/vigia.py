"""Decisão do vigia da câmera (puro): quando reiniciar o nó da webcam, e por quê.

Usado pelo robot_reaction_ros/camera_vigia.py. No robô a webcam USB cai e volta várias vezes por
minuto (mau contato/energia no hub USB 2.0) ou trava sem cair; cada reinício custa ~1–2 s de imagem.
"""
from __future__ import annotations

import glob
import os

SEM_QUADROS_S = 2.0  # sem quadros por isso (já tendo recebido algum): reinicia
# Nenhum quadro desde a subida por isso: reinicia (e de novo a cada tanto, enquanto nunca vier um).
# O reconhecimento leva ~20 s carregando o modelo antes do 1º quadro: com 15 s / 6 s o vigia
# reiniciava a câmera várias vezes à toa na subida (visto no robô em 2026-11-05).
PRIMEIRO_QUADRO_S = 30.0
CARENCIA_S = 6.0  # depois de um reinício, espera o 1º quadro antes de reiniciar de novo
WEBCAM_GLOB = "/dev/v4l/by-id/*-video-index0"


def webcam_conectada_em() -> float | None:
    """Hora da última (re)conexão da webcam USB (o link em by-id é recriado a cada uma), ou None."""
    for caminho in sorted(glob.glob(WEBCAM_GLOB)):
        if "RealSense" in caminho:
            continue
        try:
            return os.lstat(caminho).st_mtime
        except OSError:
            continue
    return None


def decidir(
    agora: float,
    inicio: float,
    ultimo_quadro: float | None,
    reiniciou_em: float | None,
    reconectou: bool,
) -> str | None:
    """Motivo para reiniciar a câmera agora, ou None.

    `reconectou`: a webcam voltou depois de cair (o nó antigo ficou preso no /dev/videoN velho):
    reinicia na hora, sem carência. Os tempos são do relógio monotônico.
    """
    if reconectou:
        return "a webcam reconectou"
    if reiniciou_em is not None and agora - reiniciou_em < CARENCIA_S:
        return None
    if ultimo_quadro is None or (reiniciou_em is not None and ultimo_quadro < reiniciou_em):
        desde = inicio if reiniciou_em is None else reiniciou_em
        # Nunca veio quadro: o reconhecimento ainda pode estar subindo; já veio: a câmera é que travou.
        limite = PRIMEIRO_QUADRO_S if ultimo_quadro is None else CARENCIA_S
        if agora - desde >= limite:
            return f"nenhum quadro em {agora - desde:.0f} s"
        return None
    if agora - ultimo_quadro >= SEM_QUADROS_S:
        return f"sem quadros há {agora - ultimo_quadro:.1f} s"
    return None
