"""F2+DOWN do scripts/robo_controle.py, sem robô: tmux e processos são dublês."""
import importlib.util
import threading
import time
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "robo_controle", Path(__file__).parents[1] / "scripts" / "robo_controle.py"
)
controle = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(controle)


class _Levantar:
    """O processo do robo_levantar.py, ainda rodando até alguém terminá-lo."""

    def __init__(self):
        self.terminado = False

    def poll(self):
        return -15 if self.terminado else None

    def terminate(self):
        self.terminado = True


@pytest.fixture
def eventos(monkeypatch):
    registro = []
    monkeypatch.setattr(controle, "tocar", lambda nome: registro.append(("bipe", nome)))
    monkeypatch.setattr(controle, "LEVANTANDO", None)
    return registro


def test_stop_reaches_the_routine_before_the_beep(monkeypatch, eventos):
    monkeypatch.setattr(controle, "sessao_de_pe", lambda: True)
    monkeypatch.setattr(controle, "rotina_rodando", lambda: False)
    monkeypatch.setattr(controle.subprocess, "run", lambda args, **_k: eventos.append(("tmux", args[1], args[-1])))
    controle._parar()
    assert eventos[0] == ("tmux", "send-keys", "C-c")
    assert ("bipe", "parar") in eventos


def test_stop_aborts_a_running_stand_up(monkeypatch, eventos):
    monkeypatch.setattr(controle, "sessao_de_pe", lambda: False)
    processo = _Levantar()
    monkeypatch.setattr(controle, "LEVANTANDO", processo)
    controle._parar()
    assert processo.terminado
    assert ("bipe", "recusado") not in eventos


def test_stop_ignores_a_stand_up_that_already_ended(monkeypatch, eventos):
    monkeypatch.setattr(controle, "sessao_de_pe", lambda: False)
    processo = _Levantar()
    processo.terminado = True
    monkeypatch.setattr(controle, "LEVANTANDO", processo)
    controle._parar()
    assert ("bipe", "recusado") in eventos  # nada para parar


def test_stop_ends_a_real_stand_up_process_and_frees_the_remote(monkeypatch, eventos, tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "robo_levantar.py").write_text("import time\nprint('levantar: comecou', flush=True)\ntime.sleep(60)\n")
    monkeypatch.setattr(controle, "REPO", str(tmp_path))
    monkeypatch.setattr(controle, "corpo_ocupado", lambda: False)
    monkeypatch.setattr(controle, "sessao_de_pe", lambda: False)
    t = threading.Thread(target=controle.levantar)
    t.start()
    while controle.LEVANTANDO is None:
        time.sleep(0.01)
    time.sleep(0.2)
    controle._parar()
    t.join(timeout=10)
    assert not t.is_alive()
    assert controle.LEVANTANDO is None
    assert eventos[-1] == ("bipe", "recusado")  # não terminou em equilíbrio


def test_combo_a_vontade_manda_o_comando(monkeypatch, eventos):
    enviados = []
    monkeypatch.setattr(controle, "enviar_voz", enviados.append)
    controle.a_vontade()
    assert enviados == ["comando:a_vontade"]
