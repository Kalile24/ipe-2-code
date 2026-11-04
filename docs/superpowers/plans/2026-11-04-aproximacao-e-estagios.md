# Aproximação, estágios e partida pelo controle — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O robô vira para a pessoa reconhecida, anda até a caixa do rosto ficar com a altura escolhida e faz a rotina; o operador escolhe os estágios e pode subir tudo pelo terminal ou pelo combo F2+UP do controle (F2+DOWN para).

**Architecture:** Lógica pura nova em `core/` (filtro de estágios, laço de aproximação em pixels, detecção de combos), testada na CI. O body_node (ROS) assina as detecções e roda o laço a ~10 Hz durante a ação `/reaction/rotina`, antes da rotina filtrada; manda as velocidades ao body_worker por uma ordem nova do protocolo JSON que nunca espera postura. Um programa sem ROS (`scripts/robo_controle.py`) lê o controle pelo SDK e chama o script.

**Tech Stack:** Python 3.8, ROS 2 Foxy (rclpy, vision_msgs), unitree_sdk2py (LocoClient, WirelessController), bash, systemd (unit de usuário).

**Spec:** `docs/superpowers/specs/2026-11-04-aproximacao-e-estagios-design.md`

## Global Constraints

- Python 3.8 (`from __future__ import annotations` em todo arquivo; sem `match`, sem `X | Y` fora de anotações).
- A rotina do Gil em `config/reactions.yaml` não muda (regra em `CLAUDE.md`).
- rclpy e o SDK da Unitree nunca no mesmo processo: só `body_worker.py`, `robo_emergencia.py` e `robo_controle.py` importam `unitree_sdk2py`.
- Estágios: `virar`, `aproximar`, `fala`, `posturas`; padrão todos; `aproximar` implica `virar`.
- `posturas` desligado tira os passos `postura` e `pausa`; `fala` desligado tira os passos `fala`.
- Velocidade sempre com `SetVelocity(vx, 0.0, vyaw, 0.5)`; nunca `vx < 0`, nunca `vy ≠ 0`.
- Padrões: `largura_imagem` 640, `altura_caixa_alvo_px` 90, `inverter_giro` false, `centro_ok` 0.15, `centro_para_andar` 0.30, `vyaw_max` 0.3, `vx` 0.2, `kp_giro` 0.6, `perda_rosto_s` 1.0, `desistir_s` 5.0, `tempo_max_s` 20.
- Desarmado: virar/aproximar só medem e registram por 2 s e dão o estágio como feito.
- Pelo controle: sempre armado, só com o robô em FSM 801 (nunca damp → em pé); recusa falada "Não estou em equilíbrio, não vou começar."
- F2+DOWN: velocidade zero na hora, cancela, a postura em andamento termina e os braços voltam.
- Combos padrão F2+UP / F2+DOWN, teclas do `keys` do `rt/wirelesscontroller`: F2 = `0x80`, UP = `0x1000`, DOWN = `0x4000` (layout do SDK: R1 0x1, L1 0x2, START 0x4, SELECT 0x8, R2 0x10, L2 0x20, F1 0x40, F2 0x80, A 0x100, B 0x200, X 0x400, Y 0x800, UP 0x1000, RIGHT 0x2000, DOWN 0x4000, LEFT 0x8000; confirmar no robô).
- Mensagens, nomes e comentários em português, como o resto do repositório.
- Testes puros: `PYTHONPATH=. .venv/bin/python -m pytest tests -q --ignore=tests/test_enroll.py --ignore=tests/test_face_engine.py`. Testes ROS: no Docker Foxy, como em `docs/guides/ros2-docker.md` (build e test com `--build-base /tmp/b --install-base /tmp/i --log-base /tmp/l`, nunca dentro de `ros2_ws/`).

## Review Focus

- Outra pessoa (do mapa ou não) aparece na frente durante a aproximação: o robô segue só a caixa com o nome do alvo; sem ela, conta como rosto perdido. → `test_other_faces_are_ignored` (Task 2).
- A câmera trava e param de chegar detecções no meio da caminhada: o robô para em `perda_rosto_s` e desiste em `desistir_s`, mesmo sem frame vazio. → `test_stale_detection_stops_then_gives_up` (Task 2).
- Cancelamento (ou F2+DOWN) chega enquanto o robô anda: velocidade zero na hora, nenhuma rotina depois. → `test_cancel_during_approach_stops_at_once_and_skips_routine` (Task 4).
- `--estagios` com nome errado ou vazio: o body_node não sobe, com mensagem dizendo os válidos. → `test_invalid_stages_fail_naming_the_valid_ones` (Task 1) e `test_invalid_stages_param_stops_the_node` (Task 4).
- Estágios que esvaziam a rotina (ex.: só `posturas` para uma rotina só de fala): a ação termina com sucesso sem fazer nada, sem erro. → `test_filter_can_leave_nothing` (Task 1) e `test_empty_filtered_routine_succeeds` (Task 4).

---

### Task 1: Estágios (parse e filtro)

**Files:**
- Create: `core/stages.py`
- Test: `tests/test_stages.py`

**Interfaces:**
- Produces:
  - `ESTAGIOS: tuple[str, ...] = ("virar", "aproximar", "fala", "posturas")`
  - `parse_stages(texto: str) -> frozenset[str]` — separa por vírgula, ignora espaços; nome desconhecido ou nenhum → `ValueError` com os válidos; `aproximar` acrescenta `virar`.
  - `filter_steps(passos: list[dict], estagios: frozenset[str]) -> list[dict]`

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from core.stages import ESTAGIOS, filter_steps, parse_stages

GIL = [
    {"postura": "sentido"}, {"postura": "continencia"},
    {"fala": "Olá, aspirante a oficial da reserva Gil, sou o Tenente Nichinica"},
    {"postura": "desc_arma"}, {"postura": "descansar"}, {"pausa": 15}, {"postura": "a_vontade"},
]

def test_all_stages_by_default_text():
    assert parse_stages("virar,aproximar,fala,posturas") == frozenset(ESTAGIOS)

def test_approach_implies_turning():
    assert parse_stages(" aproximar , fala ") == {"aproximar", "virar", "fala"}

@pytest.mark.parametrize("texto", ["", " , ", "virar,pular"])
def test_invalid_stages_fail_naming_the_valid_ones(texto):
    with pytest.raises(ValueError, match="posturas"):
        parse_stages(texto)

def test_only_speech_drops_postures_and_pauses():
    assert filter_steps(GIL, frozenset({"fala"})) == [GIL[2]]

def test_only_postures_keeps_pause_and_drops_speech():
    assert filter_steps(GIL, frozenset({"posturas"})) == [s for s in GIL if "fala" not in s]

def test_filter_can_leave_nothing():
    assert filter_steps([{"fala": "oi"}], frozenset({"posturas"})) == []

def test_movement_stages_do_not_filter_steps():
    assert filter_steps(GIL, frozenset(ESTAGIOS)) == GIL
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_stages.py -q`
Expected: FAIL (`ModuleNotFoundError: core.stages`)

- [ ] **Step 3: Implement `parse_stages` and `filter_steps` in `core/stages.py`**

Módulo puro, docstring citando a spec. `filter_steps` não revalida (a rotina já veio do `validate_steps`).

- [ ] **Step 4: Run to verify they pass**

Run: same as Step 2. Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/stages.py tests/test_stages.py
git commit -m "feat: parse and filter the routine stages"
```

---

### Task 2: Laço de aproximação em pixels

**Files:**
- Create: `core/approach.py`
- Test: `tests/test_approach.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class ApproachConfig` com os campos e padrões das Global Constraints (`largura_imagem: int = 640`, `altura_caixa_alvo_px: float = 90.0`, `inverter_giro: bool = False`, `centro_ok: float = 0.15`, `centro_para_andar: float = 0.30`, `vyaw_max: float = 0.3`, `vx: float = 0.2`, `kp_giro: float = 0.6`, `perda_rosto_s: float = 1.0`, `desistir_s: float = 5.0`, `tempo_max_s: float = 20.0`).
  - `@dataclass(frozen=True) class Comando: vx: float; vyaw: float; estado: str` — `estado` ∈ `ANDANDO = "andando"`, `SEM_ROSTO = "sem_rosto"`, `PRONTO = "pronto"`, `DESISTIU_ROSTO = "desistiu: rosto perdido"`, `DESISTIU_TEMPO = "desistiu: tempo esgotado"` (constantes do módulo). `PRONTO` e os dois `DESISTIU_*` encerram o estágio.
  - `escolher_caixa(caixas: list[tuple[str, float, float]], nome: str) -> tuple[float, float] | None` — caixas `(nome, center_x, size_y)`; devolve `(center_x, size_y)` da maior caixa com o nome, ou `None`.
  - `passo_aproximacao(cfg: ApproachConfig, aproximar: bool, caixa: tuple[float, float] | None, visto_em: float, inicio: float, agora: float) -> Comando` — `caixa` = a última caixa do alvo, `visto_em` = quando ela chegou (`inicio` se nunca chegou).

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from core.approach import (
    ANDANDO, DESISTIU_ROSTO, DESISTIU_TEMPO, PRONTO, SEM_ROSTO, ApproachConfig, Comando, escolher_caixa,
    passo_aproximacao,
)

CFG = ApproachConfig()

def _passo(caixa, aproximar=True, visto_em=0.0, agora=0.0, cfg=CFG):
    return passo_aproximacao(cfg, aproximar, caixa, visto_em, inicio=0.0, agora=agora)

def test_face_on_the_right_turns_right_with_negative_yaw():
    c = _passo((480.0, 50.0))  # desvio +0,5
    assert c.vyaw == pytest.approx(-0.3)  # -kp 0,6 × 0,5 = -0,3 (= -vyaw_max)
    assert c.vx == 0.0 and c.estado == ANDANDO  # desvio > centro_para_andar: só gira

def test_turn_is_clamped_and_can_be_inverted():
    assert _passo((640.0, 50.0)).vyaw == pytest.approx(-0.3)
    assert _passo((480.0, 50.0), cfg=ApproachConfig(inverter_giro=True)).vyaw == pytest.approx(0.3)

def test_walks_at_constant_speed_when_roughly_centred_and_far():
    c = _passo((352.0, 50.0))  # desvio +0,1
    assert c.vx == pytest.approx(0.2) and c.vyaw == 0.0  # dentro de centro_ok: não gira

def test_ready_when_centred_and_box_tall_enough():
    assert _passo((320.0, 90.0)).estado == PRONTO
    assert _passo((320.0, 90.0)).vx == 0.0

def test_turn_only_is_ready_once_centred():
    assert _passo((330.0, 10.0), aproximar=False).estado == PRONTO
    assert _passo((480.0, 10.0), aproximar=False).vx == 0.0

def test_stale_detection_stops_then_gives_up():
    assert _passo((480.0, 50.0), visto_em=0.0, agora=1.5) == Comando(0.0, 0.0, SEM_ROSTO)
    assert _passo((480.0, 50.0), visto_em=0.0, agora=5.5).estado == DESISTIU_ROSTO

def test_never_seen_gives_up_after_desistir_s():
    assert _passo(None, agora=4.0).estado == SEM_ROSTO
    assert _passo(None, agora=5.0).estado == DESISTIU_ROSTO

def test_gives_up_after_tempo_max():
    assert _passo((352.0, 50.0), visto_em=20.0, agora=20.0).estado == DESISTIU_TEMPO

def test_other_faces_are_ignored():
    caixas = [("marcos", 300.0, 120.0), ("gil", 100.0, 40.0), ("gil", 500.0, 60.0), ("desconhecido", 320.0, 200.0)]
    assert escolher_caixa(caixas, "gil") == (500.0, 60.0)
    assert escolher_caixa([("marcos", 300.0, 120.0)], "gil") is None

def test_never_walks_backwards_when_too_close():
    assert _passo((352.0, 300.0)).vx == 0.0
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_approach.py -q`
Expected: FAIL (`ModuleNotFoundError: core.approach`)

- [ ] **Step 3: Implement in `core/approach.py`**

Ordem das regras em `passo_aproximacao`: (1) `agora − inicio ≥ tempo_max_s` → `DESISTIU_TEMPO`; (2) `caixa is None` ou `agora − visto_em > perda_rosto_s` → `DESISTIU_ROSTO` se `agora − visto_em ≥ desistir_s`, senão `Comando(0, 0, SEM_ROSTO)`; (3) `desvio = (cx − largura/2)/(largura/2)`; `vyaw = 0` se `|desvio| ≤ centro_ok`, senão `clamp(−kp_giro × desvio, ±vyaw_max)`, com o sinal trocado se `inverter_giro` (vyaw positivo = anti-horário, convenção da Unitree e do ROS); (4) `vx = cfg.vx` se `aproximar` e `size_y < altura_caixa_alvo_px` e `|desvio| < centro_para_andar`, senão 0; (5) `PRONTO` se `|desvio| ≤ centro_ok` e (não `aproximar` ou `size_y ≥ altura_caixa_alvo_px`), com `vx = vyaw = 0`; senão `ANDANDO`.

- [ ] **Step 4: Run to verify they pass**

Run: same as Step 2. Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/approach.py tests/test_approach.py
git commit -m "feat: approach loop from the face box in pixels"
```

---

### Task 3: body_worker — velocidade que não espera postura, e inicialização só 801

**Files:**
- Modify: `ros2_ws/src/robot_reaction_ros/robot_reaction_ros/body_worker.py` (`G1Body`, `serve`)
- Modify: `ros2_ws/src/robot_reaction_ros/robot_reaction_ros/body_node.py` (`SubprocessBody`)
- Test: `ros2_ws/src/robot_reaction_ros/test/test_body_worker.py`

**Interfaces:**
- Consumes: protocolo atual (linhas JSON com `id`, resposta `{"id", "ok"}`).
- Produces:
  - Ordens novas **sem resposta**, atendidas na hora mesmo com uma postura em andamento: `{"cmd": "velocidade", "vx": float, "vyaw": float}` → `body.velocity(vx, vyaw)`; `{"cmd": "parar"}` → `body.stop()`.
  - `{"id": n, "cmd": "initialize", "so_equilibrio": bool}`; `G1Body.initialize(so_equilibrio: bool = False) -> bool` — com `True`, só aceita FSM 801 modo 0 (FSM 0/1 também recusa, sem damp).
  - `G1Body.velocity(vx: float, vyaw: float) -> None` = `self.robot.loco.SetVelocity(vx, 0.0, vyaw, 0.5)`; `G1Body.stop() -> None` = `self.robot.loco.StopMove()`.
  - `SubprocessBody.initialize(so_equilibrio: bool = False) -> bool`, `SubprocessBody.velocity(vx: float, vyaw: float) -> None`, `SubprocessBody.stop() -> None` — as duas últimas só escrevem a linha (lock de escrita próprio, separado do lock das chamadas com resposta); nunca esperam.

- [ ] **Step 1: Write the failing tests**

```python
def test_velocity_and_stop_are_served_while_a_posture_runs():
    # _FakeBody ganha velocity/stop que gravam em calls; posture("lenta") espera um Event
    ...  # serve() numa thread com um pipe (os.pipe); manda posture lenta, depois velocidade e parar
    assert body.calls[:3] == ["lenta", ("velocidade", 0.1, -0.2), "parar"]  # antes da postura acabar
    assert respostas == [{"id": 1, "ok": True}, ...]  # velocidade/parar não respondem

def test_initialize_balance_only_refuses_limp_robot():
    body = _g1_body((1, 0))
    assert body.initialize(so_equilibrio=True) is False
    assert not body.robot.inicializou and "equilíbrio" in body.robot.logs[-1]

def test_initialize_balance_only_accepts_801():
    body = _g1_body((801, 0))
    assert body.initialize(so_equilibrio=True) is True

def test_subprocess_body_sends_velocity_without_waiting():
    # FAKE_WORKER cuja postura "lenta" dorme 1 s; velocity() durante ela volta em < 0,1 s
    ...
```

(Os `...` são a montagem com os dublês que o arquivo já tem — `_FakeBody`, `_g1_body`, `FAKE_WORKER`; o fake ganha `velocity`/`stop`.)

- [ ] **Step 2: Run to verify they fail**

Run (Docker Foxy): `colcon test --packages-select robot_reaction_ros --pytest-args -k "velocity or balance_only"` e `colcon test-result --verbose`
Expected: FAIL

- [ ] **Step 3: Implement**

`serve`: a thread principal lê a entrada; `velocidade`/`parar` chamam o corpo ali mesmo; as outras ordens vão para uma `queue.Queue` atendida por uma thread executora, que responde (escrita na saída sob lock). Entrada fechada ou `shutdown`: põe a sentinela na fila, espera a executora, `body.shutdown()`, resposta final (como hoje). `G1Body.initialize(so_equilibrio=True)` fora do 801/0 registra `"ERRO: robô em FSM_ID=…: pelo controle só começo em equilíbrio (FSM 801)"`.

- [ ] **Step 4: Run to verify they pass**

Run: same as Step 2, sem `-k`. Expected: todos os testes do pacote PASS.

- [ ] **Step 5: Commit**

```bash
git add ros2_ws/src/robot_reaction_ros/robot_reaction_ros/body_worker.py ros2_ws/src/robot_reaction_ros/robot_reaction_ros/body_node.py ros2_ws/src/robot_reaction_ros/test/test_body_worker.py
git commit -m "feat: walking orders that never wait for a posture, balance-only start-up"
```

---

### Task 4: body_node — estágios, aproximação e parada imediata

**Files:**
- Modify: `ros2_ws/src/robot_reaction_ros/robot_reaction_ros/body_node.py` (`BodyNode`)
- Create: `ros2_ws/src/robot_reaction_ros/config/operacao.yaml`
- Modify: `ros2_ws/src/robot_reaction_ros/setup.py` (instalar `config/operacao.yaml`)
- Test: `ros2_ws/src/robot_reaction_ros/test/test_body_node.py`

**Interfaces:**
- Consumes: `parse_stages`, `filter_steps` (Task 1); `ApproachConfig`, `escolher_caixa`, `passo_aproximacao`, constantes de estado (Task 2); `SubprocessBody.initialize(so_equilibrio)`, `.velocity`, `.stop` (Task 3).
- Produces:
  - Parâmetros novos do body_node: `estagios` (str, padrão `"virar,aproximar,fala,posturas"`), `detections_topic` (padrão `/face_recognition/detections`), `so_equilibrio` (bool, padrão false) e um por campo de `ApproachConfig`, com o mesmo nome.
  - `config/operacao.yaml` no formato de parâmetros ROS (`body_node: ros__parameters: {...}`) com todos esses valores padrão (menos `armed`).
  - Status `/reaction/rotina_status` durante o estágio: `"aproximar: desvio=+0.12 caixa=74px vx=0.20 vyaw=-0.07 (andando)"` (ou `virar:`), e `"rotina de gil: desistiu: rosto perdido"` no fim.
  - `body_factory` passa a receber `(poses_dir, network_interface, rest_forward_pulse)` como hoje; a inicialização chama `body.initialize(so_equilibrio)`.

- [ ] **Step 1: Write the failing tests**

Na fixture: `make(..., estagios="...", params=[...])` e um publicador de `Detection2DArray` no nó cliente (ou chamada direta de `n._on_detections(msg)`); `_FakeBody` ganha `velocity(vx, vyaw)` e `stop()` gravando em `calls`.

```python
def test_armed_turns_then_runs_the_routine(make_node):
    # detecção do gil centralizada e alta (caixa 120 px) → PRONTO no primeiro passo
    assert body.calls[:2] == ["initialize", "stop"]  # parou ao ficar pronto
    assert "sentido" in body.calls

def test_approach_sends_velocities_until_ready(make_node):
    # gil a desvio +0,1 e 50 px, depois 120 px
    assert ("velocidade", 0.2, 0.0) in body.calls and body.calls.index("stop") < body.calls.index("sentido")

def test_lost_face_gives_up_without_greeting(make_node):  # desistir_s:=0.3
    assert not resultado.sucesso and resultado.mensagem == "desistiu: rosto perdido"
    assert "sentido" not in body.calls and body.calls[-1] == "stop"

def test_cancel_during_approach_stops_at_once_and_skips_routine(make_node):
    # cancela com o gil longe (andando); stop em < 0,2 s; nenhuma postura
    ...

def test_disarmed_only_measures_for_two_seconds(make_node):
    # desarmado, gil visível: status com "caixa=" em ~2 s, depois a rotina (dry_run), sucesso
    ...

def test_stages_filter_the_routine(make_node):  # estagios:="fala"
    assert spoken == ["Olá, aspirante"] and not [s for s in status if s.startswith("dry_run")]

def test_empty_filtered_routine_succeeds(make_node):  # estagios:="posturas", passos só de fala
    assert resultado.sucesso

def test_invalid_stages_param_stops_the_node():
    with pytest.raises(ValueError, match="posturas"):  # estagios:="pular"
        ...

def test_balance_only_failure_speaks_and_rejects_routines(make_node):  # so_equilibrio:=true, init_ok=False
    assert spoken == ["Não estou em equilíbrio, não vou começar."]
    assert not env.send()[0]
```

- [ ] **Step 2: Run to verify they fail**

Run (Docker Foxy): `colcon test --packages-select robot_reaction_ros` e `colcon test-result --verbose`
Expected: FAIL nos testes novos

- [ ] **Step 3: Implement**

- Assinatura das detecções guarda a última lista `(nome, center_x, size_y)` e o instante (`time.monotonic()`) por nome (callback group reentrante).
- No `_execute`, antes do `run_routine`: se `virar` nos estágios, laço a cada 0,1 s (`self._interromper.wait(0.1)` como espera) chamando `passo_aproximacao`, mandando `body.velocity` (armado) ou só o status (desarmado), até um estado final. Desarmado: sai como feito depois de 2 s. Em todo fim do laço (pronto, desistiu, interrompido) armado: `body.stop()`. Desistiu → resultado `sucesso=False`, `mensagem` = o estado, sem rotina.
- Rotina: `filter_steps(passos, estagios)`; lista vazia → sucesso direto.
- `_on_cancel` e `shutdown()` chamam `body.stop()` na hora (antes de esperar qualquer coisa), se armado.
- `so_equilibrio` e falha na inicialização: fala `"Não estou em equilíbrio, não vou começar."` e passa a recusar todas as rotinas (sem cair no dry-run).
- `parse_stages` no `__init__`: `ValueError` derruba o nó na partida.

- [ ] **Step 4: Run to verify they pass**

Run: same as Step 2. Expected: todos PASS

- [ ] **Step 5: Commit**

```bash
git add ros2_ws/src/robot_reaction_ros/robot_reaction_ros/body_node.py ros2_ws/src/robot_reaction_ros/config/operacao.yaml ros2_ws/src/robot_reaction_ros/setup.py ros2_ws/src/robot_reaction_ros/test/test_body_node.py
git commit -m "feat: turn and approach before the routine, stages and immediate stop"
```

---

### Task 5: Launch e script — arquivo de operação, `--estagios`, `--controle`

**Files:**
- Modify: `ros2_ws/src/robot_reaction_ros/launch/rotina.launch.py`
- Modify: `scripts/robo_rotina_cumprimento.sh`
- Modify: `scripts/robo_emergencia.py` (só o texto: "só no suporte")

**Interfaces:**
- Consumes: parâmetros do body_node (Task 4).
- Produces:
  - Launch args novos: `operacao_file` (padrão `share/robot_reaction_ros/config/operacao.yaml`), `estagios` (padrão `""` = o do arquivo), `so_equilibrio` (padrão `false`). O body_node recebe `[operacao_file, {armed, pausa_s, passo_descansar, so_equilibrio}]` mais `estagios` só se não for vazio.
  - Script: `--estagios LISTA` repassa `estagios:=LISTA`; `--controle` = armado, sem a pergunta do suporte, `so_equilibrio:=true`, sem a janela `emergencia`, e falha (exit 1) sem esperar nada interativo. Sem a caixa, `--controle` continua (a recusa falada só não toca).
  - `robo_emergencia.py`: docstring e o prompt do modo pronto dizem que o damp é só com o robô no suporte (fora dele, ele cai).

- [ ] **Step 1: Verify the launch in the container**

Run (Docker Foxy, com o workspace compilado): `ros2 launch robot_reaction_ros rotina.launch.py --show-args`
Expected: lista `operacao_file`, `estagios`, `so_equilibrio`.

- [ ] **Step 2: Smoke test the body_node with the file**

Run: `ros2 run robot_reaction_ros body_node --ros-args --params-file /tmp/i/share/robot_reaction_ros/config/operacao.yaml -p estagios:=fala` em segundo plano, depois `ros2 param get /body_node altura_caixa_alvo_px` e `ros2 param get /body_node estagios`
Expected: `Double value is: 90.0` e `String value is: fala`.

- [ ] **Step 3: Check the script**

Run: `bash -n scripts/robo_rotina_cumprimento.sh` e `scripts/robo_rotina_cumprimento.sh --pular`
Expected: sintaxe ok; a segunda sai com `Argumento desconhecido: --pular (use --armado, --controle, --estagios LISTA e/ou usb|realsense)` e exit 1.

- [ ] **Step 4: Commit**

```bash
git add ros2_ws/src/robot_reaction_ros/launch/rotina.launch.py scripts/robo_rotina_cumprimento.sh scripts/robo_emergencia.py
git commit -m "feat: operation file, stage selection and a non-interactive remote start"
```

---

### Task 6: Programa do controle (F2+UP / F2+DOWN)

**Files:**
- Create: `core/remote_combos.py`
- Create: `scripts/robo_controle.py`
- Create: `scripts/systemd/ipe-controle.service`
- Test: `tests/test_remote_combos.py`

**Interfaces:**
- Produces:
  - `F2, UP, DOWN = 0x80, 0x1000, 0x4000`; `INICIAR, PARAR = "iniciar", "parar"`.
  - `class Combos: __init__(self, combos: dict[str, int])` (nome → máscara de teclas), `update(self, keys: int) -> str | None` — devolve o nome do combo na borda em que **todas** as teclas dele ficam apertadas; segurar não repete; soltar e apertar de novo repete.
  - `scripts/robo_controle.py [--iniciar 0x1080] [--parar 0x4080] [--mostrar] [--interface eth0]`: sem ROS; `ChannelFactoryInitialize(0, iface)`, `ChannelSubscriber("rt/wirelesscontroller", WirelessController_)` com callback (sem laço ocupado: a thread principal só espera um `threading.Event`). `INICIAR` → se a sessão tmux `rotina` não existe, `subprocess.Popen([repo/scripts/robo_rotina_cumprimento.sh, "--controle"])`; senão registra e ignora. `PARAR` → `tmux send-keys -t rotina:rotina C-c` (se a sessão existe). `--mostrar` imprime `keys` em hexa a cada mudança (para confirmar os bits no robô). Log em stdout (journal).
  - `ipe-controle.service`: unit de **usuário** (`~/.config/systemd/user/`), `ExecStart=/bin/bash -lc 'source %h/ipe-2-code/scripts/ambiente_robo.sh && exec python3 %h/ipe-2-code/scripts/robo_controle.py'`, `Restart=on-failure`, `WantedBy=default.target`.

- [ ] **Step 1: Write the failing tests**

```python
from core.remote_combos import DOWN, F2, INICIAR, PARAR, UP, Combos

def _combos():
    return Combos({INICIAR: F2 | UP, PARAR: F2 | DOWN})

def test_fires_once_on_the_press_edge():
    c = _combos()
    assert [c.update(k) for k in [0, F2, F2 | UP, F2 | UP, F2 | UP]] == [None, None, INICIAR, None, None]

def test_release_and_press_again_fires_again():
    c = _combos()
    assert [c.update(k) for k in [F2 | UP, F2, F2 | UP]] == [INICIAR, None, INICIAR]

def test_extra_keys_do_not_block_the_combo():
    assert _combos().update(F2 | DOWN | 0x1) == PARAR

def test_up_alone_or_f2_alone_does_nothing():
    c = _combos()
    assert [c.update(k) for k in [UP, 0, F2, 0]] == [None] * 4
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest tests/test_remote_combos.py -q`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implement `core/remote_combos.py`, `scripts/robo_controle.py` and the unit**

`robo_controle.py` só importa o SDK dentro de `main()` (o módulo importa sem SDK). Se dois combos ficarem prontos no mesmo update, `PARAR` vence.

- [ ] **Step 4: Run to verify they pass**

Run: same as Step 2, e `python3 -m py_compile scripts/robo_controle.py`. Expected: PASS, sem erro.

- [ ] **Step 5: Commit**

```bash
git add core/remote_combos.py scripts/robo_controle.py scripts/systemd/ipe-controle.service tests/test_remote_combos.py
git commit -m "feat: start and stop the routine from the remote (F2+UP / F2+DOWN)"
```

---

### Task 7: Documentação

**Files:**
- Modify: `docs/guides/jetson-deployment.md` (seção 8)
- Modify: `docs/superpowers/specs/2026-11-04-aproximacao-e-estagios-design.md` (status: implementado, não testado no robô)
- Modify: `README.md` (linha do robô: `--estagios`, `--controle`)

- [ ] **Step 1: Write the guide changes**

Na seção 8: estágios e `--estagios`; o `operacao.yaml` (o que cada número faz, de onde copiar a tabela da spec) e como trocar de arquivo; **como escolher `altura_caixa_alvo_px`**: desarmado, pessoa parada na distância desejada, ler `caixa=…px` na janela `status`; `inverter_giro` se virar para o lado errado; partida pelo controle: robô em equilíbrio antes, F2+UP, F2+DOWN, recusa falada, `robo_controle.py --mostrar` para confirmar os bits; instalar o serviço (`mkdir -p ~/.config/systemd/user && cp …/ipe-controle.service …`, `systemctl --user enable --now ipe-controle`, `sudo loginctl enable-linger unitree`), **só depois de combinar com quem usa o robô**; `robo_emergencia.py` só no suporte.

- [ ] **Step 2: Check links and leftovers**

Run: `git grep -n "distancia_alvo\|altura_rosto\|campo_horizontal" -- docs README.md ros2_ws scripts core`
Expected: nada.

- [ ] **Step 3: Commit**

```bash
git add docs README.md
git commit -m "docs: stages, approach calibration and the remote start"
```
