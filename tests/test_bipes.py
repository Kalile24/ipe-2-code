import io
import wave

from core.bipes import PADROES, TAXA, wav


def test_every_pattern_is_a_short_valid_wav():
    for nome, padrao in PADROES.items():
        with wave.open(io.BytesIO(wav(padrao))) as w:
            assert w.getnchannels() == 1 and w.getframerate() == TAXA
            duracao = w.getnframes() / TAXA
        assert 0.1 < duracao < 0.7, nome


def test_patterns_are_distinct():
    assert len({tuple(p) for p in PADROES.values()}) == len(PADROES)
