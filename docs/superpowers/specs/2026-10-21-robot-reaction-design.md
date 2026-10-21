# Reação do robô ao reconhecer uma pessoa (Fase 2) — Design

Data: 2026-10-21.

Contexto: a Fase 1 está implantada no robô — o `face_recognition_node` (specs
`2026-09-12-ros2-node-migration-design.md` e `2026-09-18-jetson-gpu-migration-design.md`) publica
em `/face_recognition/detections` quem a webcam USB da cabeça está vendo. Este documento cobre o
passo seguinte: o robô **reagir com um movimento** quando reconhece uma pessoa específica.

Fora do escopo: áudio/TTS (o áudio embutido do G1 está com defeito — o `vui_service` cai sozinho —
e fica para depois), continência, sequência fala→gesto, rastrear ou se aproximar da pessoa, subir
no boot. O desenho já reserva o lugar do áudio (ver "Áudio no futuro").

## Fatos

- **Gestos prontos do firmware:** o `unitree_sdk2py` (1.0.1 no Python global do robô, visível no
  nosso venv por `--system-site-packages`) tem o `G1ArmActionClient` (serviço RPC `arm`,
  `ExecuteAction(id)`), com gestos como `high wave` (26), `face wave` (25), `shake hand` (27),
  `clap` (17), `hands up` (15) e `release arm` (99). Não há continência na lista.
  Fonte: `unitree_sdk2py/g1/arm/g1_arm_action_client.py` (`action_map`).
- **O exemplo oficial** (`example/g1/high_level/g1_arm_action_example.py`) chama
  `ChannelFactoryInitialize(0, <interface>)`, `SetTimeout(10.0)`, `Init()`, e depois de vários
  gestos espera ~2 s e manda `release arm`.
- **`ExecuteAction` é bloqueante** (RPC que devolve um código; 0 = sucesso, 3104 = timeout).
- **O `face_recognition_node` publica um `Detection2DArray` por frame**, vazio quando não há
  rosto; cada `Detection2D` traz o nome em `results[0].id` (`desconhecido` abaixo do limiar) e
  o score em `results[0].score`. ~42 ms por frame na Jetson (~24 fps).
- **O `~/hhhh` (outro projeto no robô)** já roda o tempo todo e comanda o braço em baixo nível
  (`G1ArmController` próprio, poses gravadas) quando os combos do joystick são apertados — entre
  eles a continência (F1 + B). Regras de convivência: `docs/guides/jetson-deployment.md`.

## Decisões

- **Movimento = gesto pronto do firmware** (`G1ArmActionClient`), não a continência do `~/hhhh`
  nem poses próprias: prova a cadeia inteira com o menor risco e sem depender do código de outro
  projeto. Trocar por continência depois é só um novo executor ou um novo gesto no mesmo nó.
- **Mapa pessoa → reação em YAML**, para várias pessoas com gestos diferentes e para ganhar o
  campo `fala` quando o áudio entrar.
- **Um tópico por executor com mensagens padrão** (`std_msgs/String`) + tópico de status para
  debug. Descartados: tópico único de evento (o mapa ficaria espalhado e cada executor voltaria a
  saber de pessoas) e ROS2 actions (pacote de interfaces `ament_cmake` e bem mais código, sem
  sequência a coordenar hoje). Se a sequência fala→gesto virar requisito, migra-se o trecho
  reação↔executores para actions sem tocar no reconhecimento.
- **O nó de gesto nasce desarmado (dry-run) e nunca troca o modo do robô.** O operador põe o
  robô em pé pelo controle; o nosso código só pede gestos.

## Arquitetura

```
face_recognition_node ──/face_recognition/detections──▶ reaction_node ──/reaction/gesture──▶ gesture_node ──RPC "arm"──▶ firmware
 (inalterado)              vision_msgs/Detection2DArray   (YAML pessoa→reação)  std_msgs/String        │
                                                                │                                     ▼
                                                                └─(futuro) /reaction/say──▶ audio_node   /reaction/gesture_status
                                                                                                        std_msgs/String
```

- **Pacote novo `ros2_ws/src/robot_reaction_ros/`** (`ament_python`, Foxy): `reaction_node`,
  `gesture_node`, `config/reactions.yaml`, `launch/robo.launch.py`. Depende de `rclpy`,
  `std_msgs`, `std_srvs`, `vision_msgs`; o launch de topo inclui o de `face_recognition_ros`
  (só `exec_depend` de launch, nenhum import Python).
- **Lógica pura em `core/reaction_policy.py`** (sem ROS, sem SDK): tabela de gestos, validação
  do mapa, confirmação e cooldowns. Os nós são cascas finas em volta dela.

### Mapa YAML

`robot_reaction_ros/config/reactions.yaml`, versionado e instalado com o pacote; o parâmetro
`reactions_file` do `reaction_node` aponta para outro.

```yaml
# nome = o mesmo do cadastro (pasta em data/known_faces/<nome>/)
gil:
  gesto: high wave
marcos:
  gesto: shake hand
```

Validado na partida do `reaction_node`; qualquer erro derruba o nó com mensagem clara:

- a raiz é um mapa `nome → {gesto: <nome do gesto>}`;
- chave desconhecida dentro da pessoa (ex.: `gesture`, `fala`) é erro — pega erro de digitação.
  `fala` passa a ser aceita quando o áudio entrar;
- o gesto tem que estar na tabela de gestos.

**Tabela de gestos** (`GESTOS` em `core/reaction_policy.py`): `nome → id` copiado do
`action_map` do `unitree_sdk2py` 1.0.1, com `release arm`. Uma cópia só, usada para validar o
YAML onde o SDK não existe (notebook, Docker) e pelo `gesture_node` para converter nome em id.
Se a Unitree mudar os ids, atualiza-se essa cópia (comentário no código diz de onde veio).

### `reaction_node` e a política

A cada `Detection2DArray`, o nó extrai `(nome, score)` de cada detecção e passa para a política
com o instante atual (`time.monotonic()`; nos testes, relógio injetado). A política devolve no
máximo uma pessoa a quem reagir; o nó publica o `gesto` dela em `/reaction/gesture`.

- **Confirmação:** contador por pessoa, +1 quando ela está na mensagem e zerado quando não está
  (mensagens vazias também contam, então são frames realmente seguidos). Dispara ao atingir
  `confirm_frames` (padrão **5**, ~0,2 s a 24 fps). `desconhecido` e quem não está no mapa são
  ignorados.
- **Cooldown por pessoa:** `person_cooldown_s` (padrão **60 s**) desde o último disparo para ela.
- **Cooldown global:** `global_cooldown_s` (padrão **10 s**) entre quaisquer dois disparos — cobre
  a duração do gesto.
- **Várias confirmadas no mesmo frame:** reage só à de maior score; as outras continuam contando e
  disparam depois do cooldown global, se ainda estiverem lá.
- Os cooldowns contam do **disparo**, não do fim do gesto: a política não lê o status.

### `gesture_node`

Único nó que fala com o firmware.

| Parâmetro | Padrão | Para quê |
|---|---|---|
| `armed` | `false` | Desarmado = dry-run |
| `network_interface` | `eth0` | Interface DDS do robô |
| `hold_s` | `2.0` | Espera entre o gesto e o `release arm` |
| `rpc_timeout_s` | `10.0` | `SetTimeout` do cliente |

- **Armar/desarmar em execução:** serviço `~/set_armed` (`std_srvs/SetBool`); cada troca é logada
  e publicada (`armed` / `disarmed`).
- **Desarmado:** não importa o SDK; loga e publica `dry_run <gesto>`.
- **Ao armar pela primeira vez:** importa o SDK e inicializa (`ChannelFactoryInitialize(0,
  network_interface)`, `G1ArmActionClient`, `SetTimeout`, `Init`). Se falhar, publica
  `failed init <erro>` e continua desarmado.
- **Comando recebido:**
  1. gesto fora de `GESTOS` → `rejected unknown '<nome>'` (nome entre aspas, para ver espaço ou string vazia); já há um gesto em andamento →
     `rejected busy` (sem fila);
  2. senão, numa thread de trabalho (o `ExecuteAction` bloqueia e não pode travar o executor do
     ROS): `started <gesto>` → `ExecuteAction(id)` → espera `hold_s` → `ExecuteAction(99)` →
     `done <gesto>`;
  3. código ≠ 0 no gesto → `failed <gesto> code=<n>` e tenta o `release arm` mesmo assim. É por
     esse código que aparece o firmware recusando (ex.: robô fora do modo certo).
- **Desarmar no meio** não interrompe o gesto em andamento; os próximos comandos já saem em
  dry-run.
- **Ao encerrar (Ctrl+C) no meio de um gesto:** tenta `release arm` antes de sair.
- **Nunca:** trocar modo de locomoção, usar `LocoClient`, controlar o braço em baixo nível.

**Status** (`/reaction/gesture_status`, `std_msgs/String`, uma linha por evento): `armed`,
`disarmed`, `dry_run <gesto>`, `started <gesto>`, `done <gesto>`, `rejected busy`,
`rejected unknown '<nome>'`, `failed <gesto> code=<n>`, `failed init <erro>`. Só para observação e
debug — nenhum nó depende dele.

### Áudio no futuro

Um `audio_node` assinando `/reaction/say` (`std_msgs/String`, a frase), o campo `fala` aceito no
YAML e o `reaction_node` publicando a frase junto com o gesto. Reconhecimento e `gesture_node`
não mudam.

### Execução

- `ros2 launch robot_reaction_ros robo.launch.py [args]` sobe tudo: inclui o
  `face_recognition.launch.py` (os argumentos dele — `camera`, `video_device`, `onnx_providers`… —
  passam pela linha de comando) e adiciona `reaction_node` e `gesture_node` (`armed` exposto como
  argumento, padrão `false`). O `face_recognition.launch.py` continua funcionando sozinho.
- `scripts/robo_tmux.sh`: a janela 0 passa a rodar o `robo.launch.py`; nova janela `gestos` com
  `ros2 topic echo /reaction/gesture_status`. O tmux continua por causa da queda de SSH, do
  ambiente obrigatório (Foxy + CycloneDDS 0.10 + venv) e das janelas de observação.
- Não vira serviço `systemd`: com gesto envolvido, nada se mexe sem alguém ter iniciado de
  propósito.

## Riscos (não validados)

1. **Duas pilhas DDS no mesmo processo:** `rclpy` (`rmw_cyclonedds_cpp` com o CycloneDDS 0.10 de
   `~/cyclonedds_ws`) e `unitree_sdk2py` (`cyclonedds` 0.10.2 do Python), ambas no domínio 0 da
   `eth0`. Mesma versão, provável que funcione. **Plano B:** o SDK roda num processo filho
   (`multiprocessing`) do `gesture_node`; a interface ROS não muda.
2. **Modo do robô em que os gestos são aceitos, e se `ExecuteAction` retorna no começo ou no fim
   do gesto** — define o sentido de `hold_s`.
3. **Convivência com o `~/hhhh`:** com o nosso nó armado, ninguém aperta os combos do joystick
   dele; avisar o autor antes do primeiro teste armado. Verificar se o serviço `arm` do firmware é
   afetado só por o processo dele estar rodando.

## Testes

**CI (puros, Python 3.8/3.10/3.12):** `tests/test_reaction_policy.py`

- mapa válido carrega; chave desconhecida, gesto fora de `GESTOS`, pessoa sem `gesto` e raiz que
  não é mapa dão erro;
- N−1 frames não disparam, N disparam; um frame sem a pessoa zera a contagem;
- cooldown por pessoa e global (relógio injetado);
- duas confirmadas no mesmo frame → a de maior score; `desconhecido` e fora do mapa nunca
  disparam.

`tests/test_future_annotations.py` passa a varrer também
`ros2_ws/src/robot_reaction_ros/robot_reaction_ros`.

**Docker (ROS Foxy, sem robô):** `ros2_ws/src/robot_reaction_ros/test/`, no padrão do
`face_recognition_ros/test/test_node.py`:

- `reaction_node`: detecções falsas → exatamente um comando em `/reaction/gesture`;
- `gesture_node` desarmado → `dry_run …`;
- `gesture_node` com cliente falso no lugar do SDK → `started`/`done`, `rejected busy`,
  `rejected unknown`, `failed … code=` com `release arm` chamado mesmo assim.

## Validação no robô

Em degraus; o seguinte só depois do anterior. O resultado de cada um entra numa seção
"Implantação no robô" deste documento.

1. **Cadeia inteira desarmada:** `robo.launch.py`; `gil` na frente da webcam → um
   `dry_run high wave` no status e outro só depois do cooldown. Ninguém mexe no braço.
2. **Gesto isolado, armado:** robô em pé, operador perto, autor do `~/hhhh` avisado; só o
   `gesture_node` com `armed:=true` e
   `ros2 topic pub --once /reaction/gesture std_msgs/msg/String "data: high wave"`. Valida os
   riscos 1 e 2.
3. **Cadeia inteira armada:** `gil` aparece → o robô acena uma vez; quem não está no mapa não
   provoca nada.

**Pronto quando:** degrau 3 funcionando, CI verde e testes do Docker passando.
