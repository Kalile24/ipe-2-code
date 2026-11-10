"""Comandos de voz do operador: tabela palavra → passos, reconhecimento e regras da posição mantida.

Puro (sem ROS): o body_node e o nó de voz são cascas em volta disto.
`sentido`, `continencia` e `atencao` (descansar) mantêm a posição até outro comando ou `a_vontade`.
"""
from __future__ import annotations

import re
import socket
import unicodedata
from dataclasses import dataclass, field

from core.reaction_policy import A_VONTADE, ReactionConfigError, validate_steps

PORTA_VOZ = 5007  # UDP em 127.0.0.1: falar_inicio, falar_fim, comando:<nome>, texto:<frase>


def enviar_voz(mensagem: str, porta: int = PORTA_VOZ) -> None:
    """Manda uma mensagem ao nó de voz; sem ninguém ouvindo, ou com erro de rede, só ignora."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.sendto(mensagem.encode("utf-8"), ("127.0.0.1", porta))
    except OSError:
        pass


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento, só letras e dígitos separados por um espaço."""
    sem_acento = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", sem_acento).split())


@dataclass(frozen=True)
class ComandosVoz:
    nao_entendi: str
    comandos: dict[str, tuple[list[str], list[dict]]]  # nome -> (palavras normalizadas, passos)
    frases: list[str] = field(default_factory=list)  # as palavras como escritas no YAML (minúsculas): a gramática


def gramatica(tabela: ComandosVoz, vocativo: str = "tenente") -> list[str]:
    """Frases que o reconhecedor (Vosk) pode devolver: cada comando sozinho, depois do vocativo, ou depois do
    vocativo e de um nome fora do vocabulário ([unk]: "Tenente Nichinica, sentido"); o resto vira [unk]."""
    return [f"{prefixo}{f}" for prefixo in ("", f"{vocativo} ", f"{vocativo} [unk] ") for f in tabela.frases] + ["[unk]"]


def carregar_comandos(raw: object) -> ComandosVoz:
    """Valida o YAML `{nao_entendi: <texto>, comandos: {<nome>: {palavras: [...], passos: [...]}}}`."""
    if not isinstance(raw, dict):
        raise ReactionConfigError(f"comandos de voz: esperado um mapa, veio {raw!r}")
    nao_entendi = raw.get("nao_entendi")
    if not isinstance(nao_entendi, str) or not nao_entendi.strip():
        raise ReactionConfigError("comandos de voz: falta 'nao_entendi' (o texto falado quando não entende)")
    brutos = raw.get("comandos")
    if not isinstance(brutos, dict) or not brutos:
        raise ReactionConfigError("comandos de voz: falta 'comandos' (mapa nome -> {palavras, passos})")
    comandos, frases = {}, []
    for nome, comando in brutos.items():
        if not isinstance(comando, dict) or set(comando) != {"palavras", "passos"}:
            raise ReactionConfigError(f"{nome}: esperado um mapa com 'palavras' e 'passos', veio {comando!r}")
        palavras = comando["palavras"]
        if not isinstance(palavras, list):
            raise ReactionConfigError(f"{nome}: 'palavras' tem que ser uma lista, veio {palavras!r}")
        frases += [" ".join(p.lower().split()) for p in palavras if isinstance(p, str)]
        palavras = [normalizar(p) for p in palavras if isinstance(p, str)]
        if not palavras or not all(palavras):
            raise ReactionConfigError(f"{nome}: 'palavras' vazia ou com palavra vazia")
        comandos[nome] = (palavras, validate_steps(nome, comando["passos"], exigir_a_vontade=False))
    return ComandosVoz(nao_entendi=nao_entendi, comandos=comandos, frases=frases)


def reconhecer(tabela: ComandosVoz, texto: str) -> str | None:
    """Nome do único comando com palavra inteira na frase; nenhum ou mais de um → None."""
    frase = f" {normalizar(texto)} "
    achados = [nome for nome, (palavras, _) in tabela.comandos.items() if any(f" {p} " in frase for p in palavras)]
    return achados[0] if len(achados) == 1 else None


def posicao_final(atual: str | None, passos: list[dict]) -> str | None:
    """Posição mantida depois dos passos: a última postura (a_vontade solta → None)."""
    for passo in reversed(passos):
        if "postura" in passo:
            return None if passo["postura"] == A_VONTADE else passo["postura"]
    return atual


def transicao(atual: str | None, passos: list[dict]) -> list[dict]:
    """Passos a executar de verdade para ir da posição `atual` até `passos`.

    - Só posturas e já está lá (ou a_vontade sem posição): nada a fazer.
    - De continência para sentido/descansar: abaixa o braço (`desc_arma`) antes; os outros
      caminhos o G1ArmController já resolve sozinho.
    """
    if all("postura" in p for p in passos) and posicao_final(atual, passos) == atual:
        return []
    primeira = next((p["postura"] for p in passos if "postura" in p), None)
    if atual == "continencia" and primeira in ("sentido", "descansar"):
        return [{"postura": "desc_arma"}] + list(passos)
    return list(passos)
