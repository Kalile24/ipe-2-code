# Comandos de voz do operador — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** o operador segura um combo do controle, diz um comando e o robô responde com posturas e falas pré-definidas, mantendo a posição até o à vontade.

**Architecture:** o `robo_controle.py` (sem ROS) avisa um nó novo, o `voz_node`, por UDP local. O `voz_node` grava com `arecord`, transcreve, acha o comando numa tabela YAML e manda a mesma ação `/reaction/rotina` com `voz=True`. O `body_node` continua único dono do corpo: guarda a posição mantida e publica o estado em `/reaction/corpo`, que suspende o cumprimento automático.

**Tech Stack:** Python 3.8, ROS 2 Foxy (rclpy, actions), `arecord` (ALSA), stdlib (`socket`, `unicodedata`, `subprocess`), pytest 7.

**Spec:** `docs/superpowers/specs/2026-11-07-comandos-de-voz-design.md`

**Base:** branch novo `comandos-de-voz` a partir de `meia-volta` (os dois mexem no `body_node`).

## Global Constraints

- Python 3.8: `from __future__ import annotations` em todo arquivo novo (há teste que confere).
- Comandos: "sentido" → sentido; "continencia" → continência; "atencao" → descansar (mantêm a posição); "apresentacao" → sentido, fala `Sou o Tenente Nichinica`, a_vontade; "a vontade" → a_vontade.
- Texto: `Não entendi, repita o comando`.
- Combos: `FALAR = F2 | Y` (segurado), `A_VONTADE = F2 | X`. O `F2` do código é o botão que os guias chamam de F3.
- Gravação: `arecord`, 16 kHz, mono, S16_LE, no máximo `GRAVACAO_MAX_S = 5.0`. **O áudio nunca vai para o disco.**
- UDP: só `127.0.0.1`, `PORTA_VOZ = 5007`. Mensagens: `falar_inicio`, `falar_fim`, `comando:<nome>`, `texto:<frase>`.
- `/reaction/corpo` (`std_msgs/String`, TRANSIENT_LOCAL, depth 1): `livre` | `rotina` | `mantendo:<postura>`.
- `/voz/estado` (`std_msgs/String`, JSON): `texto`, `comando`, `resultado` (`gravando`, `transcrevendo`, `ok`, `nao_entendi`, `recusado`), `transcricao_s`, `microfone` (bool).
- Limite de posição mantida: parâmetro `posicao_max_s = 300.0`; ao esgotar, à vontade sozinho e status `posicao mantida: tempo esgotado, a_vontade`.
- Recusa é silenciosa: nada se mexe, nada é falado, só `/voz/estado` com `recusado`.
- A voz nunca chama `velocity` nem aproximação nem meia-volta.
- Desarmado: posturas só no log, falas de verdade (como as rotinas de hoje); a posição mantida é registrada igual.
- Testes puros: `PYTHONPATH=. .venv/bin/python -m pytest tests -q`. Testes ROS: no contêiner `face-recognition-ros2:local` (`docs/guides/ros2-docker.md` §3), `colcon test --packages-select robot_reaction_ros`.

## Review Focus

1. Silêncio ou transcrição vazia: fala "não entendi", não se mexe — `test_transcricao_vazia_fala_nao_entendi` (Task 5).
2. O "soltar" do combo nunca chega (controle desligou): a gravação termina sozinha em 5 s — `test_gravacao_termina_sozinha` (Task 5).
3. Microfone ausente ou `arecord` falhando: não derruba o nó, avisa no painel — `test_sem_microfone_nao_derruba` (Task 5).
4. Whisper com erro ou demorando: conta como não entendido, sem travar os próximos comandos — `test_erro_na_transcricao_fala_nao_entendi` (Task 5).
5. Tempo-limite da posição esgota com uma rotina em andamento: não disputa o corpo — `test_tempo_limite_nao_disputa_rotina` (Task 2).

---

### Task 1: Tabela de comandos e regras puras

**Files:**
- Create: `core/comandos_voz.py`, `ros2_ws/src/robot_reaction_ros/config/comandos_voz.yaml`
- Modify: `core/reaction_policy.py` (`validate_steps`), `ros2_ws/src/robot_reaction_ros/setup.py` (instalar o YAML)
- Test: `tests/test_comandos_voz.py`, `tests/test_reaction_policy.py`

**Interfaces:**
- Produces:
  - `validate_steps(nome, passos, exigir_a_vontade: bool = True)`.
  - `PORTA_VOZ = 5007`; `enviar_voz(mensagem: str, porta: int = PORTA_VOZ) -> None` (UDP para 127.0.0.1; `OSError` só ignora).
  - `normalizar(texto: str) -> str`: minúsculas, sem acento, não alfanumérico vira espaço, espaços colapsados.
  - `@dataclass(frozen=True) ComandosVoz`: `nao_entendi: str`, `comandos: dict[str, tuple[list[str], list[dict]]]` (nome → palavras normalizadas, passos).
  - `carregar_comandos(raw: object) -> ComandosVoz`: `ReactionConfigError` se faltar `nao_entendi`, `comandos`, ou `palavras` vazia; passos por `validate_steps(nome, passos, exigir_a_vontade=False)`.
  - `reconhecer(tabela: ComandosVoz, texto: str) -> str | None`: nome do único comando com palavra inteira na frase; nenhum ou dois → `None`.
  - `transicao(atual: str | None, passos: list[dict]) -> list[dict]` e `posicao_final(atual: str | None, passos: list[dict]) -> str | None`.

- [ ] **Step 1: testes que falham**

```python
def test_normaliza_acento_e_pontuacao():
    assert normalizar("Tenente, À VONTADE!") == "tenente a vontade"

def test_reconhece_palavra_inteira():
    t = _tabela()
    assert reconhecer(t, "Tenente, sentido!") == "sentido"
    assert reconhecer(t, "ressentido") is None

def test_dois_comandos_nao_valem():
    assert reconhecer(_tabela(), "sentido e continência") is None

def test_frase_vazia():
    assert reconhecer(_tabela(), "  ") is None

def test_yaml_do_pacote_carrega_e_tem_os_cinco():
    # lê config/comandos_voz.yaml (pule com pytest.importorskip("yaml") se o venv local não tiver)
    assert set(carregar_comandos(raw).comandos) == {"sentido", "continencia", "atencao", "apresentacao", "a_vontade"}

def test_de_continencia_para_sentido_passa_por_desc_arma():
    assert transicao("continencia", [{"postura": "sentido"}]) == [{"postura": "desc_arma"}, {"postura": "sentido"}]
    assert transicao("continencia", [{"postura": "descansar"}])[0] == {"postura": "desc_arma"}

def test_de_continencia_para_a_vontade_vai_direto():
    assert transicao("continencia", [{"postura": "a_vontade"}]) == [{"postura": "a_vontade"}]

def test_mesma_posicao_nao_faz_nada():
    assert transicao("sentido", [{"postura": "sentido"}]) == []

def test_a_vontade_sem_posicao_nao_faz_nada():
    assert transicao(None, [{"postura": "a_vontade"}]) == []

def test_posicao_final():
    assert posicao_final(None, [{"postura": "sentido"}]) == "sentido"
    assert posicao_final("sentido", [{"postura": "a_vontade"}]) is None
    assert posicao_final("sentido", [{"fala": "oi"}]) == "sentido"

def test_passos_sem_a_vontade_so_com_a_opcao():  # em test_reaction_policy.py
    assert validate_steps("x", [{"postura": "sentido"}], exigir_a_vontade=False) == [{"postura": "sentido"}]
    with pytest.raises(ReactionConfigError):
        validate_steps("x", [{"postura": "sentido"}])
```

- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** implementar. `transicao` prepara `desc_arma` só quando `atual == "continencia"` e a primeira postura é `sentido` ou `descansar`: os outros caminhos o `G1ArmController` já resolve (`leave_rest_if_needed`, `return_to_balance_and_release`). Palavras do YAML: `sentido`; `continencia`; `atencao`; `apresentacao`, `apresente se`; `a vontade`.
- [ ] **Step 4:** PASS.
- [ ] **Step 5:** commit `feat: voice command table and held-position rules`.

### Task 2: Posição mantida no `body_node`

**Files:**
- Modify: `ros2_ws/src/robot_reaction_interfaces/action/Rotina.action` (Goal: `bool voz`), `ros2_ws/src/robot_reaction_ros/robot_reaction_ros/body_node.py`
- Test: `ros2_ws/src/robot_reaction_ros/test/test_body_node.py`

**Interfaces:**
- Consumes: `transicao`, `posicao_final`, `validate_steps(..., exigir_a_vontade=False)` (Task 1).
- Produces: `Rotina.Goal.voz`; `BodyNode._mantida: str | None`; publisher `/reaction/corpo` (publica `livre` na partida); parâmetro `posicao_max_s`.

- [ ] **Step 1: testes que falham** (usar `make_node`; goals com `voz=True`, `pessoa="voz"`)

```python
def test_voz_mantem_a_posicao_sem_a_vontade(make_node): ...      # calls == ["sentido"]; corpo termina "mantendo:sentido"
def test_voz_nao_aproxima_nem_faz_meia_volta(make_node): ...     # estagios com virar,meia_volta; nenhuma velocity nem meia_volta
def test_trocar_de_continencia_para_sentido(make_node): ...      # calls == ["continencia", "desc_arma", "sentido"]
def test_a_vontade_solta_a_posicao(make_node): ...               # corpo "livre", _mantida None
def test_cumprimento_recusado_com_posicao_mantida(make_node): ... # goal sem voz rejeitado
def test_postura_que_falha_limpa_a_posicao(make_node): ...       # _mantida None, corpo "livre"
def test_corpo_publica_rotina_durante_a_execucao(make_node): ...
def test_tempo_limite_faz_a_vontade(make_node): ...              # posicao_max_s:=0.1 → a_vontade chamado, status com o texto do limite
def test_tempo_limite_nao_disputa_rotina(make_node): ...         # com _busy preso, a_vontade não é chamado; tenta de novo depois
def test_ctrl_c_com_posicao_mantida_solta_os_bracos(make_node): ... # shutdown chama body.shutdown
def test_goal_de_cumprimento_ainda_exige_a_vontade(make_node): ...
```

- [ ] **Step 2:** rodar no contêiner → FAIL.
- [ ] **Step 3:** implementar. `_parse` devolve também `voz` e valida com `exigir_a_vontade=not voz`. Em `_on_goal`, goal sem `voz` com `_mantida` definida é `REJECT` com status `rotina de <pessoa> rejeitada: posicao mantida`. Em `_execute`, `voz=True` vai para `_executar_voz(passos, log) -> bool`: `run_routine(transicao(self._mantida, passos), ...)` sem `filter_steps`; sucesso → `posicao_final`, falha → `None`. Estado publicado no início (`rotina`) e no `finally` (`mantendo:<x>` ou `livre`). Timer de 1 s no grupo reentrante: passou de `posicao_max_s` e `_busy.acquire(blocking=False)` conseguiu → limpa `_idle`, `_posture("a_vontade")`, publica o status, solta.
- [ ] **Step 4:** PASS, incluindo os testes antigos.
- [ ] **Step 5:** commit `feat: body_node keeps a voice-commanded position until a_vontade`.

### Task 3: Cumprimento suspenso durante a posição mantida

**Files:**
- Modify: `ros2_ws/src/robot_reaction_ros/robot_reaction_ros/reaction_node.py`
- Test: `ros2_ws/src/robot_reaction_ros/test/test_reaction_node.py`

**Interfaces:**
- Consumes: `/reaction/corpo` (Task 2).
- Produces: `ReactionNode._mantendo: bool`.

- [ ] **Step 1: testes que falham**

```python
def test_nao_cumprimenta_com_posicao_mantida(node): ...      # detecções confirmadas, _greeted vazio
def test_volta_a_cumprimentar_quando_livre(node): ...
def test_cumprimentar_agora_recusado_com_posicao_mantida(node): ...  # set_parameters não é successful
def test_quem_aparece_na_posicao_mantida_nao_conta_como_cumprimentado(node): ...
```

- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** assinar com TRANSIENT_LOCAL; `_on_detections` usa `allow_fire=False` com `_mantendo`; `cumprimentar_agora` devolve `successful=False, reason="posicao mantida"`.
- [ ] **Step 4:** PASS.
- [ ] **Step 5:** commit `feat: suspend automatic greetings while a position is held`.

### Task 4: Combos do controle

**Files:**
- Modify: `core/remote_combos.py`, `scripts/robo_controle.py` (docstring incluída)
- Test: `tests/test_remote_combos.py`, `tests/test_robo_controle.py`

**Interfaces:**
- Consumes: `enviar_voz` (Task 1).
- Produces: `FALAR = F2 | Y`, `A_VONTADE = "a_vontade"` em `PADRAO` com `F2 | X`; `INICIO, FIM = "inicio", "fim"`; `class Segurado(mascara)` com `update(keys: int) -> str | None`.

- [ ] **Step 1: testes que falham**

```python
def test_segurado_avisa_inicio_e_fim():
    s = Segurado(F2 | Y)
    assert [s.update(k) for k in [0, F2 | Y, F2 | Y, F2, 0]] == [None, INICIO, None, FIM, None]

def test_a_vontade_e_falar_nao_colidem():
    assert PADRAO[A_VONTADE] == F2 | X and len(set(PADRAO.values()) | {FALAR}) == len(PADRAO) + 1

def test_soltar_e_apertar_avisa_de_novo(): ...

def test_combo_a_vontade_manda_o_comando(monkeypatch): ...  # em test_robo_controle.py: enviar_voz("comando:a_vontade")
```

- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** no laço de leitura, `Segurado(args.falar)` chama `enviar_voz("falar_inicio")`/`enviar_voz("falar_fim")` direto, sem passar pelo lock `ocupado`. `a_vontade` entra em `acoes`.
- [ ] **Step 4:** PASS.
- [ ] **Step 5:** commit `feat: controller combos to talk and to release the position`.

### Task 5: `voz_node`

**Files:**
- Create: `core/gravador.py`, `ros2_ws/src/robot_reaction_ros/robot_reaction_ros/voz_node.py`
- Modify: `ros2_ws/src/robot_reaction_ros/setup.py` (entry point), `ros2_ws/src/robot_reaction_ros/launch/rotina.launch.py` (nó novo)
- Test: `tests/test_gravador.py`, `ros2_ws/src/robot_reaction_ros/test/test_voz_node.py`

**Interfaces:**
- Consumes: `carregar_comandos`, `reconhecer`, `PORTA_VOZ` (Task 1); `Rotina.Goal.voz`, `/reaction/corpo` (Task 2).
- Produces:
  - `class Gravador(dispositivo: str, comando: list[str] | None = None)`: `presente() -> bool`, `iniciar() -> None`, `parar() -> bytes`. Comando padrão `["arecord", "-q", "-D", dispositivo, "-f", "S16_LE", "-r", "16000", "-c", "1", "-t", "raw"]`; uma thread acumula o stdout num `bytearray` (o pipe enche em ~2 s).
  - `class VozNode(Node)`, `__init__(self, gravador_factory=Gravador, transcrever: Callable[[bytes], str] = sem_transcricao, speak=say)`. Parâmetros: `dispositivo` (`"default"`), `comandos_file` (`""` = o do pacote), `porta` (`PORTA_VOZ`), `gravacao_max_s` (5.0), `tts_url`, `tts_timeout_s`.
  - `sem_transcricao(pcm: bytes) -> str`: levanta `RuntimeError("transcricao nao configurada")`. Fica como padrão até a Task 8.

- [ ] **Step 1: testes que falham**

```python
def test_gravador_junta_o_stdout():  # tests/test_gravador.py
    g = Gravador("x", comando=["sh", "-c", "printf abc; sleep 5"])
    g.iniciar(); time.sleep(0.2)
    assert g.parar() == b"abc"

def test_texto_vira_rotina_de_voz(node): ...          # "texto:sentido" → goal voz=True, pessoa "voz"
def test_frase_desconhecida_fala_nao_entendi(node): ...
def test_transcricao_vazia_fala_nao_entendi(node): ...
def test_erro_na_transcricao_fala_nao_entendi(node): ...
def test_gravacao_termina_sozinha(node): ...          # gravacao_max_s:=0.2 sem falar_fim → transcreve uma vez
def test_falar_fim_depois_do_limite_nao_transcreve_de_novo(node): ...
def test_sem_microfone_nao_derruba(node): ...         # iniciar levanta OSError → resultado recusado, microfone false
def test_corpo_em_rotina_recusa_em_silencio(node): ... # nada gravado, nada falado, resultado recusado
def test_goal_rejeitado_e_silencioso(node): ...
def test_comando_direto_nao_precisa_de_microfone(node): ...  # "comando:a_vontade"
def test_comando_desconhecido_e_ignorado(node): ...
def test_novo_aperto_durante_o_ciclo_e_ignorado(node): ...
def test_audio_nao_vai_para_o_disco(node, tmp_path): ...     # transcrever recebe bytes; nenhum arquivo novo no cwd
```

- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** implementar. Socket UDP em `127.0.0.1` numa thread daemon com timeout de 0,5 s, fechada no `destroy_node`. Um ciclo por vez (`gravar → transcrever → reconhecer → goal ou fala`) numa thread própria. `comando:` e `texto:` entram direto em "reconhecer/enviar". Launch ganha `voz_node` com `dispositivo` vindo do argumento `microfone` (padrão `default`).
- [ ] **Step 4:** PASS no contêiner e na suíte pura.
- [ ] **Step 5:** commit `feat: voice node from push-to-talk to the routine action`.

### Task 6: Painel

**Files:**
- Modify: `ros2_ws/src/robot_reaction_ros/robot_reaction_ros/painel_node.py`, `ros2_ws/src/robot_reaction_ros/painel/index.html`
- Test: `ros2_ws/src/robot_reaction_ros/test/test_painel_node.py`

**Interfaces:**
- Consumes: `/reaction/corpo`, `/voz/estado`, `enviar_voz`.
- Produces: `estado()["corpo"]`, `estado()["voz"]`; ação `a_vontade`.

- [ ] **Step 1: testes que falham:** `acao("a_vontade")` chama `enviar_voz("comando:a_vontade")`; `estado()` traz o último `/voz/estado` e o corpo; JSON inválido em `/voz/estado` é ignorado sem derrubar.
- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** implementar. Cartão **Voz** com o texto ouvido, o comando, o resultado e o tempo da transcrição; `segurando <postura>` quando `corpo` começa com `mantendo:`; botão **À vontade** em `cmd_de_pe`; em `problemas()`, aviso `Microfone da webcam não encontrado` quando `voz.microfone === false`.
- [ ] **Step 4:** PASS; `node --check` no script extraído; abrir o painel local num navegador e conferir o cartão e o botão.
- [ ] **Step 5:** commit `feat: panel shows voice commands and held position`.

### Task 7: Medição e guias

**Files:**
- Create: `scripts/robo_medir_voz.sh` (`arecord -l`; grava 5 s em `/dev/shm`, mostra tamanho e pico com `sox` se houver; apaga no fim)
- Modify: `docs/guides/teste-no-robo.md`, `docs/guides/operar-o-robo.md`

- [ ] **Step 1:** escrever o script; `bash -n` passa.
- [ ] **Step 2:** guias: combos F3+Y e F3+X, os cinco comandos, testar sem microfone com `python3 -c 'from core.comandos_voz import enviar_voz; enviar_voz("texto:sentido")'`, o aviso de que "Atenção" só vai para o robô depois de resolver o desequilíbrio do descansar.
- [ ] **Step 3:** suíte pura → PASS.
- [ ] **Step 4:** commit `docs: voice command measurement and operator guide`.

### Task 8: Motor de transcrição (**depende do robô; não executar agora**)

Só depois de rodar a Task 7 no robô, porque o modelo, a API e a latência do Whisper da imagem `openvoice-piper-whisper-jetson:1.0` não são conhecidos.

**Files:**
- Create: `core/transcricao.py`
- Modify: `ros2_ws/src/robot_reaction_ros/robot_reaction_ros/voz_node.py`, `scripts/robo_voz.sh` (ou script próprio)

**Interfaces:**
- Produces: `transcrever(pcm: bytes) -> str`, substituindo `sem_transcricao` como padrão do `VozNode`.

**Critério de aceite:** os cinco comandos ditos a 1–2 m com o robô em pé são reconhecidos, português, e o tempo do soltar do botão até o início da resposta fica em torno de 3 s com o reconhecimento facial rodando. Se a imagem existente não atender: faster-whisper `small` multilíngue, int8; modelos `.en` não servem.

- [ ] **Step 1:** medir e registrar o resultado na spec.
- [ ] **Step 2:** escrever o teste do `transcrever` contra um servidor falso ou um modelo mínimo, conforme o motor escolhido; rodar → FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** PASS e teste no robô com o roteiro da Task 7.
- [ ] **Step 5:** commit `feat: local speech-to-text for voice commands`.
