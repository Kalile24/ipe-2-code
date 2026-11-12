# Meia-volta volver — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** depois de uma rotina de cumprimento bem-sucedida, o robô gira 180° pela esquerda (fechado no
yaw do IMU), anda ~0,2 m e espera o operador liberar antes de cumprimentar de novo.

**Architecture:** a lógica do giro é pura (`core/meia_volta.py`). O laço roda no `body_worker`, que
tem o `LocoClient` e o `rt/lowstate` (`G1ArmController.low_state`); o `body_node` pede a ordem
`meia_volta` depois do `run_routine` quando o estágio `meia_volta` está ligado e devolve o resultado na
ação. O `reaction_node` vê esse resultado e para de cumprimentar até o operador liberar.

**Tech Stack:** Python 3.8, ROS 2 Foxy (rclpy, actions), `unitree_sdk2py`, pytest 7.

**Spec:** `docs/superpowers/specs/2026-11-07-meia-volta-design.md`

## Global Constraints

- Python 3.8: `from __future__ import annotations` em todo arquivo novo (há teste que confere).
- Giro **pela esquerda** = `vyaw` **positivo**; 180°; parar quando o girado ≥ 180° − tolerância.
- Padrões e faixas (no `operacao.yaml`, no `LIMITES_OPERACAO` e no painel):
  `vyaw_meia_volta` 0.5 (0.3–0.8), `tolerancia_meia_volta_graus` 10.0 (2–30), `passo_m` 0.2 (0–0.5,
  0 = sem passo), `vx_passo` 0.2 (0.05–0.3), `tempo_max_meia_volta_s` 12.0 (5–30).
- Os tetos `VX_MAX = 0.5`, `VYAW_MAX = 0.8` do `body_worker` continuam sendo a última barreira.
- Só move armado e inicializado; desarmado publica `dry_run meia_volta` e não chama o corpo.
- PARAR/cancelamento/Ctrl+C interrompem giro e passo na hora; ao sair por qualquer motivo, `StopMove`.
- Textos de status (o painel depende dos prefixos): `meia_volta: girando (girado=+93°)`,
  `meia_volta: fim`, `meia_volta: falhou (<motivo>)`, `dry_run meia_volta`;
  no `reaction_node`: `aguardando o operador (Liberar cumprimentos)`.
- Resultado da ação com meia-volta: `sucesso=True` (a pessoa foi cumprimentada) e
  `mensagem="meia_volta: fim"` ou `"meia_volta: falhou (<motivo>)"` ou `"meia_volta: dry_run"`.
- Testes puros: `PYTHONPATH=. .venv/bin/python -m pytest tests -q`. Testes ROS: no contêiner
  `face-recognition-ros2:local` (`docs/guides/ros2-docker.md` §3), `cd ros2_ws && colcon build
  --symlink-install && colcon test --packages-select robot_reaction_ros && colcon test-result --verbose`.

## Review Focus

1. O yaw passa por ±π no meio do giro (começa em +170°): o girado tem que somar os incrementos, não
   subtrair ângulos absolutos — teste `test_girado_atravessa_mais_menos_pi` (Task 2).
2. PARAR durante o giro: o laço do worker não pode voltar a mandar velocidade depois do `parar` —
   teste `test_parar_interrompe_meia_volta` (Task 3).
3. `low_state` ainda `None` ou yaw `nan` logo no começo: não gira, falha `sem angulo` — teste
   `test_sem_angulo_nao_gira` (Task 2) e `test_meia_volta_sem_low_state` (Task 3).
4. Rotina falhou, foi interrompida ou a aproximação desistiu: nada de meia-volta e nada de espera —
   `test_rotina_que_falha_nao_faz_meia_volta` (Task 4).
5. `data/operacao.yaml` salvo antes do estágio existir: ganha `meia_volta` ao subir, mas um salvo
   depois, sem a caixa marcada, fica sem — `test_migra_estagios_*` (Task 1).

---

### Task 1: Estágio `meia_volta`, parâmetros e migração

**Files:**
- Modify: `core/stages.py` (ESTAGIOS; nova `migrar_estagios`)
- Modify: `core/approach.py:21-33` (`LIMITES_OPERACAO`)
- Modify: `ros2_ws/src/robot_reaction_ros/config/operacao.yaml`
- Modify: `ros2_ws/src/robot_reaction_ros/launch/rotina.launch.py` (`_body_node`)
- Test: `tests/test_stages.py`, `tests/test_approach.py`

**Interfaces:**
- Produces: `ESTAGIOS = ("virar", "aproximar", "fala", "posturas", "meia_volta")`;
  `migrar_estagios(valores: dict) -> dict` (cópia; acrescenta `meia_volta` a `valores["estagios"]` só
  quando `"vyaw_meia_volta" not in valores` e `meia_volta` não está na lista; sem `estagios`, devolve
  igual).

- [ ] **Step 1: testes que falham**

```python
def test_meia_volta_e_um_estagio_valido():
    assert parse_stages("posturas,meia_volta") == frozenset({"posturas", "meia_volta"})

def test_migra_estagios_de_arquivo_antigo():
    assert migrar_estagios({"estagios": "virar,fala"})["estagios"] == "virar,fala,meia_volta"

def test_migra_estagios_nao_mexe_em_arquivo_novo():
    v = {"estagios": "virar,fala", "vyaw_meia_volta": 0.5}
    assert migrar_estagios(v) == v

def test_migra_estagios_nao_duplica():
    assert migrar_estagios({"estagios": "fala,meia_volta"})["estagios"] == "fala,meia_volta"

def test_limites_da_meia_volta():  # em tests/test_approach.py
    assert LIMITES_OPERACAO["vyaw_meia_volta"] == (0.3, 0.8)
    with pytest.raises(ValueError):
        validar_operacao({"passo_m": 0.6})
```

- [ ] **Step 2:** `PYTHONPATH=. .venv/bin/python -m pytest tests/test_stages.py tests/test_approach.py -q` → FAIL.
- [ ] **Step 3:** implementar; `LIMITES_OPERACAO` ganha as cinco faixas da Global Constraints.
  `operacao.yaml`: `estagios: "virar,aproximar,fala,posturas,meia_volta"` e os cinco campos com
  comentário curto. No launch, `_body_node`: se o `operacao_file` existe e `estagios` não veio pela
  linha de comando, ler o YAML (`["/**"]["ros__parameters"]`) e, se `migrar_estagios` mudar a lista,
  pôr a lista migrada em `sobrescritas["estagios"]`.
- [ ] **Step 4:** testes passam (o teste existente que confere `VYAW_MAX`/`VX_MAX` contra os limites
  também).
- [ ] **Step 5:** commit `feat: meia_volta stage, its parameters and migration of saved settings`.

### Task 2: Laço puro do giro (`core/meia_volta.py`)

**Files:**
- Create: `core/meia_volta.py`
- Test: `tests/test_meia_volta.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class MeiaVoltaConfig` com os cinco campos e padrões da Global Constraints.
  - `GIRANDO, CHEGOU, FALHOU_TEMPO, FALHOU_SENTIDO, FALHOU_SEM_ANGULO` (strings:
    `"girando"`, `"chegou"`, `"tempo esgotado"`, `"girou para o lado errado"`, `"sem angulo"`).
  - `acumular(girado: float, yaw_anterior: float, yaw: float) -> float` — soma `yaw - yaw_anterior`
    reduzido a (−π, π].
  - `passo_giro(cfg: MeiaVoltaConfig, girado: float | None, decorrido_s: float) -> tuple[float, str]` —
    `(vyaw, estado)`; `vyaw = cfg.vyaw_meia_volta` só em `GIRANDO`, senão 0.0. Ordem das regras:
    girado `None`/não finito → `FALHOU_SEM_ANGULO`; girado ≥ π − tol → `CHEGOU`; girado ≤ −tol →
    `FALHOU_SENTIDO`; decorrido ≥ `tempo_max_meia_volta_s` → `FALHOU_TEMPO`; senão `GIRANDO`.
  - `duracao_passo(cfg) -> float` — `passo_m / vx_passo` (0.0 se `passo_m == 0`).

- [ ] **Step 1: testes que falham**

```python
def test_girado_atravessa_mais_menos_pi():
    g = acumular(0.0, math.radians(170), math.radians(-170))
    assert g == pytest.approx(math.radians(20))

def test_gira_para_a_esquerda_ate_chegar():
    cfg = MeiaVoltaConfig()
    assert passo_giro(cfg, math.radians(90), 2.0) == (0.5, GIRANDO)
    assert passo_giro(cfg, math.radians(171), 4.0) == (0.0, CHEGOU)

def test_lado_errado_falha():
    assert passo_giro(MeiaVoltaConfig(), math.radians(-11), 1.0)[1] == FALHOU_SENTIDO

def test_tempo_esgotado():
    assert passo_giro(MeiaVoltaConfig(), math.radians(90), 12.0)[1] == FALHOU_TEMPO

def test_sem_angulo_nao_gira():
    assert passo_giro(MeiaVoltaConfig(), float("nan"), 0.0) == (0.0, FALHOU_SEM_ANGULO)
    assert passo_giro(MeiaVoltaConfig(), None, 0.0) == (0.0, FALHOU_SEM_ANGULO)

def test_duracao_do_passo():
    assert duracao_passo(MeiaVoltaConfig()) == pytest.approx(1.0)
    assert duracao_passo(MeiaVoltaConfig(passo_m=0.0)) == 0.0
```

- [ ] **Step 2:** rodar `tests/test_meia_volta.py` → FAIL (módulo não existe).
- [ ] **Step 3:** implementar como nas Interfaces.
- [ ] **Step 4:** PASS.
- [ ] **Step 5:** commit `feat: pure half-turn loop closed on the IMU yaw`.

### Task 3: Ordem `meia_volta` no `body_worker` e no `SubprocessBody`

**Files:**
- Modify: `ros2_ws/src/robot_reaction_ros/robot_reaction_ros/body_worker.py` (`G1Body.meia_volta`,
  `G1Body.yaw`, `serve`, docstring do protocolo)
- Modify: `ros2_ws/src/robot_reaction_ros/robot_reaction_ros/body_node.py` (`SubprocessBody.meia_volta`,
  `MEIA_VOLTA_TIMEOUT_S`, `ESPERA_ROTINA_S`)
- Modify: `ros2_ws/src/robot_reaction_ros/launch/rotina.launch.py` (`sigterm_timeout` e comentário)
- Test: `ros2_ws/src/robot_reaction_ros/test/test_body_worker.py`

**Interfaces:**
- Consumes: `MeiaVoltaConfig`, `acumular`, `passo_giro`, `duracao_passo` (Task 2).
- Produces:
  - Protocolo: `→ {"id": n, "cmd": "meia_volta", "cfg": {<campos do MeiaVoltaConfig>}}`
    `← {"id": n, "ok": true}` ou `{"id": n, "ok": false, "erro": "<estado de falha ou 'interrompida'>"}`.
  - `G1Body.yaw() -> float | None` — `low_state.imu_state.rpy[2]`; `None` sem `low_state`.
  - `G1Body.meia_volta(cfg: MeiaVoltaConfig, interromper: threading.Event, log) -> str` — `""` se deu
    certo, senão o motivo. Laço a 50 Hz: `acumular` + `passo_giro`; em `GIRANDO`,
    `self.velocity(0.0, vyaw)`; depois do `CHEGOU`, `StopMove`, e se `duracao_passo > 0`,
    `self.velocity(cfg.vx_passo, 0.0)` a cada 0,1 s por `duracao_passo`; `StopMove` num `finally`.
    Log a cada ~0,5 s: `meia_volta: girando (girado=+93°)`.
  - `serve`: `parar` (thread de leitura) faz `interromper.set()` além do `body.stop()`; a executora
    limpa o evento antes de começar uma `meia_volta`. Um corpo sem `meia_volta` responde
    `ok: false, erro: "ordem desconhecida"`, como hoje.
  - `SubprocessBody.meia_volta(cfg: dict) -> tuple[bool, str]` — `_call` que devolve também o `erro`;
    timeout `MEIA_VOLTA_TIMEOUT_S = 60.0`. `ESPERA_ROTINA_S` soma `MEIA_VOLTA_TIMEOUT_S`; o
    `sigterm_timeout` do launch sobe na mesma medida (330 → 390) e o comentário refaz a conta.

- [ ] **Step 1: testes que falham** (o `_FakeBody` ganha `meia_volta(cfg, interromper, log)` que
  registra a chamada e espera `interromper` por até 5 s quando `cfg.passo_m == 0.42`)

```python
def test_meia_volta_vai_para_a_executora_e_responde():
    # serve com {"id": 1, "cmd": "meia_volta", "cfg": {...}} → resposta {"id": 1, "ok": true}

def test_parar_interrompe_meia_volta():
    # meia_volta lenta em andamento; "parar" na entrada → interromper.set(), body.stop() chamado,
    # resposta {"id": 1, "ok": false, "erro": "interrompida"} em menos de 1 s

def test_meia_volta_sem_low_state():
    # G1Body com robot falso cujo low_state é None → meia_volta devolve "sem angulo" e nunca chamou SetVelocity

def test_g1body_meia_volta_para_ao_chegar():
    # robot falso: rpy[2] avança 0,1 rad a cada SetVelocity; devolve "" e o último comando de loco é StopMove
```

- [ ] **Step 2:** rodar no contêiner → FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** PASS, e os testes antigos do worker continuam passando.
- [ ] **Step 5:** commit `feat: body_worker half-turn order, interruptible by stop`.

### Task 4: `body_node` executa a meia-volta depois da rotina

**Files:**
- Modify: `ros2_ws/src/robot_reaction_ros/robot_reaction_ros/body_node.py` (parâmetros,
  `_execute`, novo `_fazer_meia_volta`, padrão do parâmetro `estagios`)
- Test: `ros2_ws/src/robot_reaction_ros/test/test_body_node.py`

**Interfaces:**
- Consumes: `MeiaVoltaConfig` (Task 2), `SubprocessBody.meia_volta` (Task 3).
- Produces: `BodyNode._fazer_meia_volta(log) -> str` — a `mensagem` do resultado
  (`"meia_volta: fim"`, `"meia_volta: falhou (<motivo>)"`, `"meia_volta: dry_run"`). Parâmetros
  declarados a partir de `fields(MeiaVoltaConfig)`, como o `ApproachConfig`. Padrão do parâmetro
  `estagios` = o do `operacao.yaml`.

- [ ] **Step 1: testes que falham** (dublê de corpo ganha `meia_volta(cfg) -> (True, "")`)

```python
def test_armado_faz_meia_volta_depois_da_rotina(make_node):
    # estagios="posturas,meia_volta" → chamadas: [..., "a_vontade", "meia_volta"];
    # result.sucesso is True e result.mensagem == "meia_volta: fim"

def test_meia_volta_que_falha_ainda_conta_como_cumprimento(make_node):
    # dublê devolve (False, "tempo esgotado") → sucesso True, mensagem "meia_volta: falhou (tempo esgotado)"

def test_rotina_que_falha_nao_faz_meia_volta(make_node):
    # postura "falha" → "meia_volta" não chamada, sucesso False

def test_desarmado_so_registra_meia_volta(make_node):
    # status contém "dry_run meia_volta"; mensagem "meia_volta: dry_run"

def test_sem_estagio_nao_faz_meia_volta(make_node):
    # estagios="posturas" → mensagem "" como hoje

def test_cancelar_durante_meia_volta_para_o_corpo(make_node):
    # dublê com meia_volta lenta; cancelamento → body.stop chamado, resultado cancelado
```

- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** implementar: em `_execute`, só quando `ok` e `"meia_volta" in self._estagios` e não
  `self._interromper.is_set()`, chamar `_fazer_meia_volta` e usar o retorno como `mensagem`
  (com `sucesso` mantido `True`). Status `meia_volta: fim` / `meia_volta: falhou (...)`.
- [ ] **Step 4:** PASS (todos os testes antigos do `body_node` também).
- [ ] **Step 5:** commit `feat: body_node runs the half-turn after a successful routine`.

### Task 5: `reaction_node` espera o operador depois da meia-volta

**Files:**
- Modify: `ros2_ws/src/robot_reaction_ros/robot_reaction_ros/reaction_node.py` (`_on_result`,
  `_on_detections`, `_on_set_parameters`, publisher de status)
- Test: `ros2_ws/src/robot_reaction_ros/test/test_reaction_node.py`

**Interfaces:**
- Produces: `ReactionNode._aguardando_operador: bool`. Liga quando o resultado tem `sucesso` e
  `mensagem.startswith("meia_volta")`. Enquanto ligado, `allow_fire=False` no `update` (a política
  continua acompanhando quem aparece). Desliga com `liberar` (qualquer valor válido) ou quando
  `automatico` é ligado. `cumprimentar_agora` funciona mesmo aguardando (ação explícita do operador)
  e desliga a espera. Ao ligar, publica `aguardando o operador (Liberar cumprimentos)` em
  `/reaction/rotina_status` (decisão do Claude: o mesmo tópico que o painel já lê).

- [ ] **Step 1: testes que falham**

```python
def test_depois_da_meia_volta_nao_cumprimenta_sozinho(node): ...
def test_liberar_volta_a_cumprimentar(node): ...
def test_ligar_automatico_volta_a_cumprimentar(node): ...
def test_cumprimentar_agora_funciona_aguardando(node): ...
def test_resultado_sem_meia_volta_nao_espera(node): ...
```

- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** implementar.
- [ ] **Step 4:** PASS.
- [ ] **Step 5:** commit `feat: wait for the operator after the half-turn`.

### Task 6: Painel

**Files:**
- Modify: `ros2_ws/src/robot_reaction_ros/robot_reaction_ros/painel_node.py` (`CAMPOS_OPERACAO`,
  `estagio`, `operacao` aplica `migrar_estagios` ao conteúdo do arquivo salvo antes do `update`)
- Modify: `ros2_ws/src/robot_reaction_ros/painel/index.html` (`ETAPAS`, `GRUPOS`)
- Test: `ros2_ws/src/robot_reaction_ros/test/test_painel_node.py`

**Interfaces:**
- Consumes: `migrar_estagios` (Task 1); prefixos de status da Global Constraints.
- Produces: `estagio("meia_volta: girando (girado=+93°)") == "fazendo meia-volta"`,
  `estagio("aguardando o operador (Liberar cumprimentos)") == "aguardando o operador"`.

- [ ] **Step 1: testes que falham:** os dois `estagio(...)` acima; `operacao()` com um arquivo salvo
  `{"estagios": "fala,posturas"}` devolve `estagios == "fala,posturas,meia_volta"`; com
  `{"estagios": "fala", "vyaw_meia_volta": 0.5}` devolve `"fala"`; `salvar_operacao` aceita e grava
  os cinco campos novos.
- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** implementar. `ETAPAS` ganha
  `['meia_volta', 'Meia-volta', 'Depois do cumprimento, gira 180° pela esquerda e dá um passo à frente; depois espera Liberar cumprimentos.']`;
  `GRUPOS` ganha `['Meia-volta', [...]]` com os cinco campos (rótulo, unidade, ajuda curta).
- [ ] **Step 4:** PASS. Abrir o painel local (sem robô) e conferir a caixa e o grupo novos.
- [ ] **Step 5:** commit `feat: panel half-turn stage and settings`.

### Task 7: Medição no robô e guias

**Files:**
- Create: `scripts/robo_medir_giro.py` (só leitura: assina `rt/lf/lowstate` pelo SDK e imprime
  `imu_state.rpy[2]` em graus e o girado acumulado com `acumular`, a 10 Hz; sem nenhum comando ao robô)
- Modify: `docs/guides/teste-no-robo.md` (passo zero: medir o yaw girando pelo controle, esquerda e
  direita, e 30 s parado; depois a meia-volta desarmada, no suporte não — fora dele, com espaço atrás)
- Modify: `docs/guides/operar-o-robo.md` (estágio Meia-volta, "aguardando o operador", Liberar
  cumprimentos, e o que fazer se ela falhar)

- [ ] **Step 1:** escrever o script e conferir `python3 scripts/robo_medir_giro.py --help` no notebook
  (o import do SDK só acontece no `main`).
- [ ] **Step 2:** atualizar os dois guias.
- [ ] **Step 3:** suíte pura inteira: `PYTHONPATH=. .venv/bin/python -m pytest tests -q` → PASS.
- [ ] **Step 4:** commit `docs: half-turn measurement script and operator guide`.
