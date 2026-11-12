"""Formulário de operação do painel: um data/operacao.yaml antigo não pode impedir de salvar."""
import threading
import time
import types
from collections import deque

import pytest
import yaml
from rcl_interfaces.msg import ParameterType, ParameterValue

from robot_reaction_ros import painel_node as painel_mod
from robot_reaction_ros.painel_node import PainelNode


def _yaml(caminho, parametros):
    caminho.write_text(yaml.safe_dump({"/**": {"ros__parameters": parametros}}))


def _painel(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    _yaml(tmp_path / "config" / "operacao.yaml", {"vx": 0.2, "vyaw_min": 0.3, "centro_chegada": 0.3})
    monkeypatch.setattr(painel_mod, "get_package_share_directory", lambda _pacote: str(tmp_path))
    painel = PainelNode.__new__(PainelNode)  # sem o __init__: não precisa de ROS rodando
    painel._operacao_file = str(tmp_path / "operacao.yaml")
    return painel


def test_saved_file_older_than_a_new_field_shows_the_package_value(tmp_path, monkeypatch):
    painel = _painel(tmp_path, monkeypatch)
    _yaml(tmp_path / "operacao.yaml", {"vx": 0.1})
    assert painel.operacao() == {"vx": 0.1, "vyaw_min": 0.3, "centro_chegada": 0.3}


def test_form_saves_over_a_file_older_than_a_new_field(tmp_path, monkeypatch):
    painel = _painel(tmp_path, monkeypatch)
    _yaml(tmp_path / "operacao.yaml", {"vx": 0.1})
    painel.salvar_operacao({"vyaw_min": "0.25"})
    salvo = yaml.safe_load((tmp_path / "operacao.yaml").read_text())["/**"]["ros__parameters"]
    assert salvo == {"vx": 0.1, "vyaw_min": 0.25, "centro_chegada": 0.3}


def _pessoas(painel_mod, tmp_path, monkeypatch, nos=()):
    painel = _painel(tmp_path, monkeypatch)
    (tmp_path / "config" / "reactions.yaml").write_text(
        'gil:\n  passos:\n    - fala: "oi"\naderson:\n  passos:\n    - fala: "oi"\n'
    )
    monkeypatch.setattr(painel_mod, "ARQ_REACOES", str(tmp_path / "reactions.yaml"))
    monkeypatch.setattr(painel_mod, "DB_BASE", str(tmp_path / "identity_db"))
    painel.get_node_names = lambda: list(nos)
    return painel


def _banco(tmp_path, *nomes):
    import numpy as np

    from core.identity_store import IdentityStore

    store = IdentityStore(str(tmp_path / "identity_db"), model_name=painel_mod.MODEL_NAME)
    for nome in nomes:
        store.enroll(nome, [np.array([1.0, 0.0])])
    store.save()


def test_people_list_shows_photos_and_routines(tmp_path, monkeypatch):
    painel = _pessoas(painel_mod, tmp_path, monkeypatch)
    _banco(tmp_path, "gil", "ze_batista")
    assert painel.pessoas() == [
        {"nome": "aderson", "fotos": 0, "rotina": True, "padrao": True},
        {"nome": "gil", "fotos": 1, "rotina": True, "padrao": True},
        {"nome": "ze_batista", "fotos": 1, "rotina": False, "padrao": False},
    ]


def test_new_person_gets_the_default_routine(tmp_path, monkeypatch):
    painel = _pessoas(painel_mod, tmp_path, monkeypatch)
    assert painel.salvar_pessoa("ana", "capitã", "")["ok"] is True
    salvo = yaml.safe_load((tmp_path / "reactions.yaml").read_text())
    assert salvo["ana"]["passos"][2] == {"fala": "Olá, capitã Ana, sou o Tenente Nichinica"}
    assert "ana" in painel.pessoas_com_rotina()


def test_panel_cannot_change_a_package_routine(tmp_path, monkeypatch):
    painel = _pessoas(painel_mod, tmp_path, monkeypatch)
    assert painel.salvar_pessoa("gil", "general", "")["ok"] is False
    assert not (tmp_path / "reactions.yaml").exists()


def test_invalid_key_is_refused(tmp_path, monkeypatch):
    painel = _pessoas(painel_mod, tmp_path, monkeypatch)
    assert painel.salvar_pessoa("Ana Maria", "capitã", "")["ok"] is False


def test_removing_needs_the_routine_stopped(tmp_path, monkeypatch):
    painel = _pessoas(painel_mod, tmp_path, monkeypatch, nos=["face_recognition_node"])
    _banco(tmp_path, "ze_batista")
    assert painel.remover_pessoa("ze_batista")["ok"] is False
    assert painel.pessoas()[-1]["fotos"] == 1


def test_removing_clears_photos_and_added_routine(tmp_path, monkeypatch):
    painel = _pessoas(painel_mod, tmp_path, monkeypatch)
    _banco(tmp_path, "gil", "ana")
    painel.salvar_pessoa("ana", "capitã", "")
    assert painel.remover_pessoa("ana")["ok"] is True
    assert [p["nome"] for p in painel.pessoas()] == ["aderson", "gil"]


def test_removing_a_package_person_keeps_the_routine_and_drops_the_photos(tmp_path, monkeypatch):
    painel = _pessoas(painel_mod, tmp_path, monkeypatch)
    _banco(tmp_path, "gil")
    assert painel.remover_pessoa("gil")["ok"] is True
    assert {"nome": "gil", "fotos": 0, "rotina": True, "padrao": True} in painel.pessoas()


def test_speaker_that_does_not_connect_is_not_saved(tmp_path, monkeypatch):
    painel = _pessoas(painel_mod, tmp_path, monkeypatch)
    arquivo = tmp_path / "caixa.txt"
    monkeypatch.setattr(painel_mod, "ARQ_CAIXA", str(arquivo))
    monkeypatch.setattr(painel_mod, "_comando", lambda *a, **k: "Connected: no")
    assert painel.usar_caixa("11:22:33:44:55:66")["ok"] is False
    assert not arquivo.exists()


def test_speaker_that_connects_is_saved_and_can_go_back(tmp_path, monkeypatch):
    painel = _pessoas(painel_mod, tmp_path, monkeypatch)
    arquivo = tmp_path / "caixa.txt"
    monkeypatch.setattr(painel_mod, "ARQ_CAIXA", str(arquivo))
    monkeypatch.setattr(painel_mod, "tocar", lambda _nome: None)
    monkeypatch.setattr(painel_mod, "_comando", lambda *a, **k: "Connected: yes\n1 bluez_sink.11_22_33_44_55_66.a2dp_sink x\n2 bluez_sink.A8_AA_CD_C6_5C_A3.a2dp_sink y")
    assert painel.usar_caixa("11:22:33:44:55:66")["ok"] is True
    assert arquivo.read_text().strip() == "11:22:33:44:55:66"
    assert painel.usar_caixa("isto nao e um mac")["ok"] is False
    painel.usar_caixa(painel_mod.CAIXA_PADRAO)
    assert not arquivo.exists()


def _so_operacao(tmp_path, monkeypatch):
    return _painel(tmp_path, monkeypatch)


def test_form_refuses_a_speed_above_the_limit_and_keeps_the_file(tmp_path, monkeypatch):
    painel = _so_operacao(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="vx"):
        painel.salvar_operacao({"vx": "2"})
    assert not (tmp_path / "operacao.yaml").exists()


def test_form_refuses_text_in_a_number(tmp_path, monkeypatch):
    painel = _so_operacao(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="vx"):
        painel.salvar_operacao({"vx": "abc"})


def test_walking_lines_are_joined_and_a_state_change_opens_a_new_one():
    status = deque(maxlen=200)
    for _ in range(300):
        painel_mod.registrar_status(status, "aproximar: desvio=+0.10 caixa=70px vx=0.20 vyaw=0.00 (andando)", 1.0)
    painel_mod.registrar_status(status, "aproximar: sem rosto (sem_rosto)", 2.0)
    painel_mod.registrar_status(status, "aproximar: desvio=+0.10 caixa=71px vx=0.20 vyaw=0.00 (andando)", 3.0)
    painel_mod.registrar_status(status, "fala: oi", 4.0)
    painel_mod.registrar_status(status, "fala: oi", 5.0)
    assert [(s[1].rsplit("(", 1)[-1], s[2]) for s in status] == [("andando)", 300), ("sem_rosto)", 1), ("andando)", 1), ("fala: oi", 1), ("fala: oi", 1)]


def _painel_armado():
    painel = PainelNode.__new__(PainelNode)
    painel._lock = threading.Lock()
    painel._status = deque(maxlen=200)
    painel._armado = None
    painel._params = {}
    painel._get_corpo = None
    painel.get_logger = lambda: types.SimpleNamespace(info=lambda *_: None)
    return painel


def _status(painel, texto):
    painel._on_status(types.SimpleNamespace(data=texto))


def test_armed_stays_true_while_walking_fills_the_history():
    painel = _painel_armado()
    _status(painel, "pronto: em equilíbrio, esperando reconhecimento")
    for i in range(500):  # cada linha diferente: nem juntar salvaria a busca antiga no histórico
        _status(painel, f"linha {i}")
    assert painel.armado({"body_node"}) is True


def test_a_disarmed_start_after_an_armed_one_shows_disarmed():
    painel = _painel_armado()
    _status(painel, "pronto: em equilíbrio, esperando reconhecimento")
    _status(painel, "desarmado: posturas só no log, fala de verdade")
    assert painel.armado({"body_node"}) is False


def test_without_body_node_it_is_not_armed_and_forgets_the_old_announcement():
    painel = _painel_armado()
    _status(painel, "pronto: em equilíbrio, esperando reconhecimento")
    assert painel.armado(set()) is False
    assert painel._armado is None


def test_panel_started_after_the_announcement_asks_the_node_and_unknown_is_not_false():
    painel = _painel_armado()
    painel._chamar = lambda *a: types.SimpleNamespace(values=[ParameterValue(type=ParameterType.PARAMETER_BOOL, bool_value=True)])
    assert painel.armado({"body_node"}) is True
    painel = _painel_armado()
    painel._chamar = lambda *a: None
    assert painel.armado({"body_node"}) is None


def _painel_com_script(tmp_path, monkeypatch, corpo):
    painel = _painel_armado()
    painel._subindo, painel._parando = threading.Event(), threading.Event()
    painel._subida_erro = None
    painel.get_node_names = lambda: []
    (tmp_path / "scripts").mkdir()
    script = tmp_path / "scripts" / "robo_rotina_cumprimento.sh"
    script.write_text("#!/bin/bash\n" + corpo)
    script.chmod(0o755)
    monkeypatch.setattr(painel_mod, "REPO", str(tmp_path))
    monkeypatch.setattr(painel_mod, "sessao_de_pe", lambda: False)
    return painel


def _espera_subir(painel):
    fim = time.monotonic() + 10
    while painel._subindo.is_set() and time.monotonic() < fim:
        time.sleep(0.01)
    assert not painel._subindo.is_set()


def test_failed_start_reports_the_last_line_of_the_script(tmp_path, monkeypatch):
    painel = _painel_com_script(tmp_path, monkeypatch, 'echo "[1/3] Caixa"\necho "ERRO: o hhhh está rodando"\nexit 1\n')
    assert painel.acao("subir_desarmado").startswith("subindo")
    _espera_subir(painel)
    assert painel._subida_erro == "ERRO: o hhhh está rodando"
    assert "falha ao subir" in painel._status[-1][1]


def test_start_that_leaves_something_running_does_not_hang(tmp_path, monkeypatch):
    # O script termina e deixa um processo de pé com a saída herdada, como o servidor de voz.
    painel = _painel_com_script(tmp_path, monkeypatch, "sleep 30 &\nexit 0\n")
    painel.acao("subir_armado")
    _espera_subir(painel)
    assert painel._subida_erro is None


def test_stop_without_a_session_says_what_to_do(monkeypatch, tmp_path):
    painel = _painel_com_script(tmp_path, monkeypatch, "exit 0\n")
    monkeypatch.setattr(painel_mod, "_comando", lambda *a, **k: "")
    assert painel.acao("parar") == "nenhuma rotina de pé"
    painel.get_node_names = lambda: ["body_node"]
    assert "à mão" in painel.acao("parar")
    monkeypatch.setattr(painel_mod, "_comando", lambda *a, **k: "4242\n")
    assert "combo de parar" in painel.acao("parar")


def test_second_stop_press_does_not_send_a_second_ctrl_c(monkeypatch, tmp_path):
    painel = _painel_com_script(tmp_path, monkeypatch, "exit 0\n")
    monkeypatch.setattr(painel_mod, "sessao_de_pe", lambda: True)
    enviados = []
    monkeypatch.setattr(painel_mod.subprocess, "run", lambda args, **k: enviados.append(args))
    trava = threading.Event()
    monkeypatch.setattr(painel_mod, "fechar_sessao_quando_terminar", lambda: trava.wait(5))
    assert painel.acao("parar").startswith("parando")
    assert "já está parando" in painel.acao("parar")
    assert len(enviados) == 1
    trava.set()


@pytest.mark.parametrize("origem, host, ok", [
    (None, "10.42.0.1:8080", True),                   # curl, script
    ("http://10.42.0.1:8080", "10.42.0.1:8080", True),
    ("https://site-qualquer.com", "10.42.0.1:8080", False),
    ("null", "10.42.0.1:8080", False),
])
def test_only_the_panel_itself_can_post(origem, host, ok):
    assert painel_mod.mesma_origem(origem, host) is ok


def test_too_many_photos_are_refused_before_touching_the_bank():
    painel = _painel_armado()
    assert painel.cadastrar("gil", ["x"] * (painel_mod.FOTOS_MAX + 1), adicionar=True)["ok"] is False


def test_operation_info_gives_defaults_and_limits(tmp_path, monkeypatch):
    info = _so_operacao(tmp_path, monkeypatch).operacao_info()
    assert info["padrao"]["vx"] == 0.2 and info["limites"]["vx"] == (0.05, 0.5)


def test_real_webcam_format_is_read_and_missing_tool_is_not_an_error():
    fmt = "Format Video Capture:\n\tWidth/Height      : 640/480\n\tPixel Format      : 'YUYV' (YUYV 4:2:2)\n"
    parm = "Streaming Parameters Video Capture:\n\tFrames per second: 30.000 (30/1)\n"
    assert painel_mod.ler_formato_webcam(fmt, parm) == {"largura": 640, "altura": 480, "fps": 30}
    assert painel_mod.ler_formato_webcam("", "") is None


def test_half_turn_status_lines_have_a_stage_name():
    assert painel_mod.estagio("meia_volta: girando (girado=+93°)") == "fazendo meia-volta"
    assert painel_mod.estagio("pronto: cumprimentos liberados") == "pronto"
    assert painel_mod.estagio("dry_run meia_volta") == "fazendo meia-volta"
    assert painel_mod.estagio("aguardando o operador (Liberar cumprimentos)") == "aguardando o operador"


def test_saved_file_from_before_the_half_turn_gains_the_stage(tmp_path, monkeypatch):
    painel = _painel(tmp_path, monkeypatch)
    (tmp_path / "config" / "operacao.yaml").write_text(
        yaml.safe_dump({"/**": {"ros__parameters": {"estagios": "fala,posturas", "vyaw_meia_volta": 0.5}}}))
    _yaml(tmp_path / "operacao.yaml", {"estagios": "fala,posturas"})
    assert painel.operacao()["estagios"] == "fala,posturas,meia_volta"
    _yaml(tmp_path / "operacao.yaml", {"estagios": "fala", "vyaw_meia_volta": 0.5})
    assert painel.operacao()["estagios"] == "fala"


def test_form_saves_the_half_turn_fields(tmp_path, monkeypatch):
    painel = _painel(tmp_path, monkeypatch)
    novos = {"vyaw_meia_volta": 0.4, "tolerancia_meia_volta_graus": 12.0, "passo_m": 0.1, "vx_passo": 0.15,
             "tempo_max_meia_volta_s": 15.0}
    _yaml(tmp_path / "config" / "operacao.yaml", {"vx": 0.2, "vyaw_meia_volta": 0.5, "tolerancia_meia_volta_graus": 10.0, "passo_m": 0.2,
                                                      "vx_passo": 0.2, "tempo_max_meia_volta_s": 12.0})
    painel.salvar_operacao({k: str(v) for k, v in novos.items()})
    salvo = yaml.safe_load((tmp_path / "operacao.yaml").read_text())["/**"]["ros__parameters"]
    assert {k: salvo[k] for k in novos} == novos


def _painel_vivo(monkeypatch):
    painel = PainelNode.__new__(PainelNode)
    painel._lock = threading.Lock()
    painel._quadros, painel._status, painel._deteccoes, painel._deteccao_em = deque(), deque(), [], 0.0
    painel._parando, painel._subindo = threading.Event(), threading.Event()
    painel._image_topic, painel._operacao_alterada_em = "/imagem", 0.0
    painel._corpo, painel._voz, painel._subida_erro = "livre", {}, None
    painel.get_node_names = lambda: ["body_node", "voz_node"]
    painel.count_publishers = lambda _t: 0
    painel.webcam, painel.caixa, painel.pessoas = (lambda *a: {"reiniciar": False}), (lambda *a: {}), (lambda *a: [])
    painel._get_rec = painel._get_corpo = None
    painel._param_fixo = lambda *a: None
    painel.armado = lambda nos: None
    painel.param_reacao = lambda nome: None
    monkeypatch.setattr(painel_mod, "sessao_criada", lambda: None)
    monkeypatch.setattr(painel_mod, "sessao_de_pe", lambda: False)
    return painel


def test_state_carries_the_last_voice_state_and_the_body(monkeypatch):
    painel = _painel_vivo(monkeypatch)
    painel._on_corpo(types.SimpleNamespace(data="mantendo:sentido"))
    painel._on_voz(types.SimpleNamespace(data='{"texto": "sentido", "resultado": "ok", "microfone": true}'))
    e = painel.estado()
    assert e["corpo"] == "mantendo:sentido"
    assert e["voz"]["texto"] == "sentido" and e["voz"]["microfone"] is True


def test_invalid_voice_json_is_ignored(monkeypatch):
    painel = _painel_vivo(monkeypatch)
    painel._on_voz(types.SimpleNamespace(data='{"texto": "a"}'))
    for lixo in ("{quebrado", "[1, 2]", "null"):
        painel._on_voz(types.SimpleNamespace(data=lixo))
    assert painel.estado()["voz"] == {"texto": "a"}


def test_relax_button_sends_the_voice_command(monkeypatch):
    painel = _painel_vivo(monkeypatch)
    enviados = []
    monkeypatch.setattr(painel_mod, "enviar_voz", enviados.append)
    painel.get_node_names = lambda: ["voz_node"]
    assert painel.acao("a_vontade") == "à vontade enviado"
    assert enviados == ["comando:a_vontade"]
    painel.get_node_names = lambda: []  # sem o nó de voz, não finge sucesso
    assert "fora do ar" in painel.acao("a_vontade")
    assert enviados == ["comando:a_vontade"]


def test_order_buttons_send_their_voice_command(monkeypatch):
    painel = _painel_vivo(monkeypatch)
    enviados = []
    monkeypatch.setattr(painel_mod, "enviar_voz", enviados.append)
    assert painel.acao("sentido") == "sentido enviado"
    assert enviados == ["comando:sentido"]


def _painel_estagios(tmp_path, monkeypatch, nos, resultado="ok"):
    painel = _painel(tmp_path, monkeypatch)
    _yaml(tmp_path / "config" / "operacao.yaml", {"estagios": "virar,fala", "vyaw_meia_volta": 0.5, "vx": 0.2, "vyaw_min": 0.3, "centro_chegada": 0.3})
    painel.get_node_names = lambda: nos
    painel._params, painel._set_corpo, painel._operacao_alterada_em = {}, None, 0.0
    painel._set_param = lambda *a: resultado
    return painel


def test_stages_apply_now_and_are_not_pending_when_the_body_is_up(tmp_path, monkeypatch):
    painel = _painel_estagios(tmp_path, monkeypatch, ["body_node"])
    assert painel.aplicar_estagios("fala") == {"ok": True, "mensagem": "valendo já"}
    assert painel.operacao()["estagios"] == "fala"
    assert painel._operacao_alterada_em == 0.0
    assert painel._params[("body_node", "estagios")][0] == "fala"


def test_stages_refused_by_the_body_are_not_saved(tmp_path, monkeypatch):
    painel = _painel_estagios(tmp_path, monkeypatch, ["body_node"], "rotina em andamento: tente quando terminar")
    antes = painel.operacao()["estagios"]
    assert painel.aplicar_estagios("fala")["ok"] is False
    assert painel.operacao()["estagios"] == antes


def test_stages_with_the_robot_stopped_wait_for_the_next_start(tmp_path, monkeypatch):
    painel = _painel_estagios(tmp_path, monkeypatch, [])
    assert painel.aplicar_estagios("fala")["mensagem"] == "vale na próxima subida"
    assert painel.aplicar_estagios("nada")["ok"] is False


def test_state_drops_voice_and_held_position_when_their_nodes_are_gone(monkeypatch):
    painel = _painel_vivo(monkeypatch)
    painel._on_corpo(types.SimpleNamespace(data="mantendo:sentido"))
    painel._on_voz(types.SimpleNamespace(data='{"microfone": false}'))
    painel.get_node_names = lambda: []
    e = painel.estado()
    assert e["corpo"] == "livre" and e["voz"] == {}
    painel.get_node_names = lambda: ["body_node"]
    e = painel.estado()
    assert e["corpo"] == "mantendo:sentido" and e["voz"] == {}
    painel.get_node_names = lambda: ["voz_node"]
    e = painel.estado()
    assert e["corpo"] == "livre" and e["voz"] == {"microfone": False}


def test_speech_text_is_saved_cleaned_and_a_bad_one_keeps_the_old(tmp_path, monkeypatch):
    from core import discurso

    arquivo = str(tmp_path / "discurso.txt")
    monkeypatch.setattr(discurso, "ARQUIVO", arquivo)
    monkeypatch.setattr(discurso.ler, "__defaults__", (arquivo,))
    monkeypatch.setattr(discurso.salvar, "__defaults__", (arquivo,))
    painel = PainelNode.__new__(PainelNode)
    painel._status = deque(maxlen=10)
    assert painel.discurso()["texto"] == discurso.PADRAO
    assert painel.salvar_discurso("  Olá,\n banca. ") == {"ok": True, "texto": "Olá, banca.", "mensagem": "salvo: vale na próxima fala"}
    assert painel.salvar_discurso("   ")["ok"] is False
    assert painel.discurso()["texto"] == "Olá, banca."
    assert "discurso" in painel_mod.ORDENS


def test_webcam_enrollment_warns_waits_then_asks_and_is_refused_during_a_routine(monkeypatch):
    painel = PainelNode.__new__(PainelNode)
    painel._lock = threading.Lock()
    painel._corpo = "rotina"
    assert painel.cadastrar("bianco", [], webcam=True)["ok"] is False
    ordem = []
    monkeypatch.setattr(painel_mod, "say", lambda texto: ordem.append(("fala", texto)))
    monkeypatch.setattr(painel_mod.time, "sleep", lambda s: ordem.append(("espera", s)))
    pedidos = []
    painel._cadastrar = None
    painel._chamar = lambda cliente, pedido, timeout: pedidos.append(pedido) or types.SimpleNamespace(ok=True, mensagem="ok")
    painel.pessoas_com_rotina = lambda: {"bianco"}
    painel._corpo = "mantendo:sentido"  # armado e parado: pode
    assert painel.cadastrar("bianco", [], webcam=True)["ok"] is True
    assert ordem == [("fala", "Olhe para a câmera"), ("espera", painel_mod.CAPTURA_S)]
    assert pedidos[0].da_webcam is True and list(pedidos[0].fotos) == []


def test_panel_state_module_reads_the_battery_file(tmp_path, monkeypatch):
    from core import bateria

    arquivo = str(tmp_path / "bat.txt")
    bateria.gravar(37, arquivo=arquivo)
    assert painel_mod.bateria.ler(arquivo) == 37 and painel_mod.bateria.MINIMO == 10
