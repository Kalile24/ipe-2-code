"""Combos do controle físico do G1 (sem ROS, sem SDK): bits dos botões e disparo na borda.

Botões no `wireless_remote` (40 bytes) do `rt/lowstate`, bytes 2–3, `uint16` little-endian — o
`xKeySwitchUnion` da doc oficial (UNITREE_G1_base_documentacao/MD/unitree_official_G1_developer/
250_remote_control_data.md). O exemplo Python oficial chama o bit 0x80 de F3; a doc C++, de F2.
Spec: docs/superpowers/specs/2026-11-04-aproximacao-e-estagios-design.md
"""
from __future__ import annotations

R1, L1, START, SELECT, R2, L2, F1, F2 = 0x1, 0x2, 0x4, 0x8, 0x10, 0x20, 0x40, 0x80
A, B, X, Y, UP, RIGHT, DOWN, LEFT = 0x100, 0x200, 0x400, 0x800, 0x1000, 0x2000, 0x4000, 0x8000

INICIAR, AGORA, AUTOMATICO, PARAR = "iniciar", "agora", "automatico", "parar"
DAMP, LEVANTAR, A_VONTADE = "damp", "levantar", "a_vontade"
PADRAO = {INICIAR: F2 | UP, AGORA: F2 | RIGHT, AUTOMATICO: F2 | LEFT, PARAR: F2 | DOWN,
          DAMP: F2 | B, LEVANTAR: F2 | A, A_VONTADE: F2 | X}
FALAR = F2 | Y  # segurado enquanto o operador fala; não é ação, por isso fora do PADRAO (ver Segurado)
INICIO, FIM = "inicio", "fim"
# Só disparam se o combo continuar apertado por SEGURAR_S: o damp derruba o robô fora do suporte, e
# o L2+B da Unitree não faz damp no modo de equilíbrio 801 (testado em 2026-11-05).
SEGURAR = (DAMP, LEVANTAR)
SEGURAR_S = 1.5
LEITURA_RECENTE_S = 0.5  # o rt/lf/lowstate chega muitas vezes por segundo: mais velho que isso, parou


def botoes(wireless_remote: bytes | list[int]) -> int:
    return wireless_remote[2] | wireless_remote[3] << 8


def segue_apertado(keys: int | None, mascara: int, recebido_em: float, agora: float) -> bool:
    """O combo continua apertado, segundo uma leitura recente? Sem leitura nova não dá para saber
    que não soltou, e o damp derrubaria o robô: conta como solto."""
    return keys is not None and keys & mascara == mascara and agora - recebido_em <= LEITURA_RECENTE_S


class Combos:
    """Devolve o nome do combo na borda em que todas as teclas dele ficam apertadas (segurar não
    repete; soltar e apertar de novo repete). Dois combos na mesma borda: PARAR vence."""

    def __init__(self, combos: dict[str, int]) -> None:
        self._combos = combos
        self._apertados: set[str] = set()

    def update(self, keys: int) -> str | None:
        agora = {nome for nome, mascara in self._combos.items() if keys & mascara == mascara}
        novos = agora - self._apertados
        self._apertados = agora
        if not novos:
            return None
        return PARAR if PARAR in novos else sorted(novos)[0]


class Segurado:
    """Avisa só as bordas de um combo segurado: INICIO ao apertar, FIM ao soltar (None no resto)."""

    def __init__(self, mascara: int) -> None:
        self._mascara = mascara
        self._apertado = False

    def update(self, keys: int) -> str | None:
        apertado = keys & self._mascara == self._mascara
        mudou, self._apertado = apertado != self._apertado, apertado
        return (INICIO if apertado else FIM) if mudou else None
