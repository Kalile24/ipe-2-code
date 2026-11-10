from __future__ import annotations

import json
import sys
import types

import pytest


@pytest.fixture
def vosk_falso(monkeypatch, tmp_path):
    """Um módulo `vosk` falso: guarda a gramática e devolve o texto programado."""
    estado = {"respostas": []}

    class Rec:
        def __init__(self, modelo, taxa, gramatica):
            estado["taxa"], estado["gramatica"] = taxa, gramatica
            self.audio = b""

        def AcceptWaveform(self, pcm):
            self.audio += pcm
            return bool(estado["respostas"])

        def FinalResult(self):
            estado["audio"], self.audio = self.audio, b""
            return json.dumps({"text": estado["respostas"].pop(0)})

        def Result(self):
            return self.FinalResult()

        def Reset(self):
            estado["zerou"] = True

    mod = types.SimpleNamespace(SetLogLevel=lambda n: None, Model=lambda caminho: caminho, KaldiRecognizer=Rec)
    monkeypatch.setitem(sys.modules, "vosk", mod)
    return estado, str(tmp_path)


def test_passa_a_gramatica_com_acento_e_devolve_o_texto(vosk_falso):
    from core.vosk_voice import Transcritor

    estado, modelo = vosk_falso
    t = Transcritor(["atenção", "[unk]"], modelo=modelo)
    assert estado["taxa"] == 16000 and json.loads(estado["gramatica"]) == ["atenção", "[unk]"]
    assert "atenção" in estado["gramatica"]  # sem ç: com escape o Vosk não acha a palavra
    estado["respostas"] = ["tenente atenção", "[unk]"]
    assert t(b"\x01\x00") == "tenente atenção" and estado["audio"] == b"\x01\x00"
    assert t(b"\x02\x00") == ""  # [unk] = não entendeu


def test_sem_audio_nem_reconhece(vosk_falso):
    from core.vosk_voice import Transcritor

    _, modelo = vosk_falso
    assert Transcritor(["sentido"], modelo=modelo)(b"") == ""


def test_sem_modelo_diz_onde_procurar(vosk_falso, tmp_path):
    from core.vosk_voice import Transcritor

    with pytest.raises(RuntimeError, match="jetson-deployment"):
        Transcritor(["sentido"], modelo=str(tmp_path / "nao_existe"))


def test_fluxo_devolve_a_frase_fechada_e_usa_a_gramatica_propria(vosk_falso):
    from core.vosk_voice import Transcritor

    estado, modelo = vosk_falso
    fluxo = Transcritor(["sentido", "[unk]"], modelo=modelo).fluxo(["tenente sentido", "[unk]"])
    assert json.loads(estado["gramatica"]) == ["tenente sentido", "[unk]"]
    assert fluxo.aceitar(b"\x01\x00") is None  # ainda no meio da frase
    estado["respostas"] = ["tenente sentido"]
    assert fluxo.aceitar(b"\x02\x00") == "tenente sentido"
    estado["respostas"] = ["[unk]"]
    assert fluxo.aceitar(b"\x03\x00") is None
    fluxo.zerar()
    assert estado["zerou"]
