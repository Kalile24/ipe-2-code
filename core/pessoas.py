"""Pessoas além das do pacote: rotina padrão (mesmo gesto, muda só o tratamento) e o mapa completo.

O config/reactions.yaml do pacote é o mapa de sempre; o data/reactions.yaml, só do robô e escrito
pelo painel, acrescenta pessoas. Sem ele (ou com ele quebrado) o robô funciona só com o do pacote.
"""
from __future__ import annotations

import os

from core.reaction_policy import ReactionConfigError, load_reactions

TRATAMENTO_MAX = 80


def nome_falado(chave: str) -> str:
    """'ze_batista' → 'Ze Batista': como o nome soa quando ninguém escreveu outro."""
    return chave.replace("_", " ").title()


def rotina_padrao(tratamento: str, nome: str) -> dict:
    """O gesto de sempre, com a fala no padrão do Gil: só troca o tratamento e o nome."""
    tratamento, nome = tratamento.strip(), nome.strip()
    if not tratamento or not nome or len(tratamento) > TRATAMENTO_MAX or len(nome) > TRATAMENTO_MAX:
        raise ValueError("preencha o tratamento e o nome (até 80 caracteres)")
    if "\n" in tratamento or "\n" in nome:
        raise ValueError("o tratamento e o nome têm que ter uma linha só")
    return {"passos": [
        {"postura": "sentido"},
        {"postura": "continencia"},
        {"fala": f"Olá, {tratamento} {nome}, sou o Tenente Nichinica"},
        {"postura": "desc_arma"},
        {"postura": "a_vontade"},
    ]}


def carregar_reacoes(base: str, extra: str) -> tuple[dict, str | None]:
    """(mapa, aviso). Erro em `base` derruba quem chamou; erro em `extra` só vira aviso, e as
    pessoas do pacote sempre vencem: o que o painel escreve nunca muda a rotina de quem já existe."""
    import yaml

    with open(base) as f:
        reacoes = load_reactions(yaml.safe_load(f))
    if not extra or not os.path.exists(extra):
        return reacoes, None
    try:
        with open(extra) as f:
            bruto = yaml.safe_load(f)
        extras = load_reactions(bruto) if bruto else {}
    except (ReactionConfigError, yaml.YAMLError, OSError) as exc:
        return reacoes, f"{extra} ignorado: {exc}"
    return {**extras, **reacoes}, None
