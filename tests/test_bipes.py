import io
import wave

import core.bipes
from core.bipes import PADROES, TAXA, tocar, wav


def test_every_pattern_is_a_short_valid_wav():
    for nome, padrao in PADROES.items():
        with wave.open(io.BytesIO(wav(padrao))) as w:
            assert w.getnchannels() == 1 and w.getframerate() == TAXA
            duracao = w.getnframes() / TAXA
        assert 0.1 < duracao < 0.7, nome


def test_patterns_are_distinct():
    assert len({tuple(p) for p in PADROES.values()}) == len(PADROES)


def test_a_beep_that_cannot_play_never_raises(monkeypatch):
    # O bipe vem antes de parar/damp: erro aqui não pode impedir a ação.
    def sem_espaco(*_a, **_k):
        raise OSError("disco cheio")

    monkeypatch.setattr(core.bipes.shutil, "which", lambda _nome: "/usr/bin/paplay")
    monkeypatch.setattr(core.bipes.tempfile, "NamedTemporaryFile", sem_espaco)
    tocar("parar")
