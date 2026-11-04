# Rotina de cumprimento: posturas militares + fala — Design

Data: 2026-10-29. Implantado e testado armado no robô em 2026-10-30.
Contexto: continua a Fase 2 (`2026-10-21-robot-reaction-design.md`).

Objetivo: rodando um script à mão (não no boot — o robô é usado por outras pessoas), o robô fica
em equilíbrio esperando; ao reconhecer o Gil: **sentido → continência → "Olá, aspirante a oficial
da reserva Gil, sou o Tenente Nichinica" → descansar arma → descansar → 15 s → à vontade**, como
um gesto militar, sem repetir à toa. O descansar arma entre a continência e o descansar é o
caminho que o código do ~/hhhh já faz (F1+B → F1+A → F1+X).

## Fatos (inspeção de 2026-10-29)

- `~/hhhh/movimentos_militares.py` lê o joystick e chama o `G1ArmController` de
  `~/hhhh/g1_arm_calibration_gui_v29.py`: controle de baixo nível em `rt/arm_sdk` a 50 Hz, poses
  JSON em `~/hhhh/poses/`, mãos Inspire por Modbus. Os combos: F1+UP inicializar
  (`initialize_to_balance`: damp → FSM 4 → R2+A virtual → FSM 801), F1+Y sentido (velocidade
  0,7), F1+X descansar, F1+B continência (2,0), F1+A desc arma (1,4), F1+RIGHT equilíbrio
  (`return_to_balance_and_release`). Ele não tem outra entrada além do joystick.
- O `movimentos_militares.py` parado não publica no `arm_sdk`; só depois de um combo.
- Fala: `POST http://127.0.0.1:5005/synthesize {"text"}` no contêiner `openvoice-piper`
  (voz `pt_BR-faber-medium`); o servidor toca com `paplay` na saída padrão (caixa Bluetooth
  KD-833) e **só responde depois de tocar**.
- O alto-falante da cabeça (`AudioClient`) responde 3104 até a `GetVolume` com 15 s de timeout.
- O venv do projeto no robô já importa o `G1ArmController` (tkinter, pymodbus 3.6.9, SDK).

## Decisões

- **Mesmo movimento do `~/hhhh`, com o código copiado para cá** (2026-11-03; até então era
  importado por `sys.path`): `robot_reaction_ros/g1_arm_controller.py` é o `G1ArmController` sem a
  GUI, com a espera do FSM 4 do `movimentos_militares.py`, e as poses ficam em
  `robot_reaction_ros/poses/`. Mesmas velocidades dos combos. Detalhes e o que mudou:
  `docs/hhhh/README.md`. Gestos do firmware não
  fazem sentido/descansar. O `movimentos_militares.py` não sobe junto (um dono do braço).
- **`body_node`**: único dono do braço e da voz. Desarmado por padrão (fala, posturas no log);
  `armed` só na partida, e armar inicializa o robô (damp → em pé → equilíbrio, no suporte).
  Ctrl+C espera o passo atual e devolve os braços.
- **YAML**: cada pessoa tem `passos` (`postura`/`fala`/`pausa`); `gesto` (firmware) saiu em 2026-11-04.
  Rotina que mexe o braço tem que terminar a última postura em `a_vontade`.
- **Repetição**: a mesma pessoa só de novo depois de 5 min **e** de ter saído da frente por 5 s
  seguidos (ficar parado na frente nunca repete; rosto virado não conta como saída). Comando
  manual de teste: `ros2 param set /reaction_node liberar <nome|todos>`
  (`scripts/robo_liberar_cumprimento.sh`).
- **Fala que falha não para o movimento; postura que falha encerra e tenta `a_vontade`.**
- **Processo à parte para o braço**: rclpy e o SDK da Unitree no mesmo processo falham
  (`channel factory init error`, CycloneDDS com duas configurações). O body_node abre o
  `body_worker` (sem ROS), dono do G1ArmController. O gesture_node, que tinha o mesmo problema, foi removido em 2026-11-04.
- **Emergência pelo computador** (`scripts/robo_emergencia.py`): damp e mata o worker; testado
  com o robô em pé no suporte em 2026-10-30.
- **Nome escrito como soa**: "Nichinica" (o Piper lê "Nixinica" como "ksi").

## Revisão de 2026-11-04 (depois do merge do PR #3)

- **Ação ROS 2 no lugar do tópico**: `/reaction/rotina` é a ação `robot_reaction_interfaces/Rotina`
  (pacote novo, ament_cmake). O body_node aceita uma rotina por vez e recusa enquanto inicializa ou
  executa outra; o reaction_node só dá a pessoa como cumprimentada se a rotina foi aceita, e não
  cumprimenta ninguém enquanto ela roda. Com o body_node fora do ar, a pessoa também não conta
  (`ReactionPolicy.forget`). O status
  continua em `/reaction/rotina_status` e vai também no feedback da ação.
- **Cancelar ou Ctrl+C**: termina o passo atual, faz o `a_vontade` (se os braços saíram do
  equilíbrio) e solta o arm_sdk. Uma `pausa` acaba na hora (espera no evento de parada).
- **Pipe com o body_worker**: cada ordem leva um `id` e só a resposta com ele vale (uma resposta
  atrasada depois de um timeout não é confundida com a da ordem seguinte); uma ordem por vez.
- **Tempos**: postura até 120 s; o Ctrl+C espera até 250 s (postura + a_vontade) + 70 s do
  shutdown do worker; `sigterm_timeout` de 330 s no `rotina.launch.py`.
- **Inicialização armada só começa pelo damp se o robô já está mole** (FSM 0 ou 1). Em equilíbrio
  (FSM 801, rodada anterior), aproveita sem damp; em pé em qualquer outro modo, recusa (o damp o
  derrubaria fora do suporte).
- **Passo para frente do descansar** (SetVelocity 0,12 m/s, compensação de equilíbrio do ~/hhhh):
  continua ligado (testado em 2026-10-30), desligável com `passo_descansar:=false`.
- **`G1ArmController.shutdown`** devolve os braços antes de parar a thread de controle (no ~/hhhh,
  parar a thread primeiro deixava o retorno ao equilíbrio sem ninguém movendo os braços).
- **Caminho dos gestos do firmware removido** (`gesture_node`, `robo.launch.py`, `robo_tmux.sh`,
  `gesto` no YAML): não armava (`channel factory init error`) e ninguém no mapa o usava. Está no
  histórico do git (PR #2) e no ramo `feat/robot-reaction`. Se voltar, volta como passo `gesto`
  executado pelo body_worker. O `robo_rotina_cumprimento.sh` desarmado e sem a caixa substitui o
  `robo_tmux.sh` para testar só o reconhecimento.

## Descartado

- **Gestos do firmware na rotina:** não fazem sentido/continência/descansar.
- **Alto-falante da cabeça:** `AudioClient` responde 3104 (o `vui_service` cai, ver a spec de
  2026-10-21); a caixa Bluetooth funciona.
- **Subir no boot:** o robô é compartilhado; a rotina roda só quando alguém executa o script.
- **Repetir por tempo fixo (60 s):** cumprimentava de novo quem ficasse parado na frente.

## Validado sem hardware

- `tests/test_reaction_policy.py`: mapa com `passos`, regra 5 min + saída, `release`.
- `tests/test_routine.py`: ordem, pausas (0,5 s automática; `pausa` explícita a substitui),
  falha de postura solta os braços, fala que falha não para o movimento, parada no meio.
- `tests/test_piper_voice.py`: POST ao servidor Piper (falso) e erros.
- `ros2_ws/src/robot_reaction_ros/test/test_body_node.py`, `test_body_worker.py`,
  `test_reaction_node.py`: com dublês do corpo e da voz (precisam de rclpy: rodam no robô ou no
  Docker; o `ambiente_robo.sh` é obrigatório — sem CycloneDDS o rclpy trava com `bad_alloc`).

## Implantação no robô (2026-10-29/30)

- Desarmado: reconheceu o gil, falou pela caixa, posturas só no log; parado na frente não
  repetiu; `robo_liberar_cumprimento.sh gil` liberou na hora.
- Armado, primeira tentativa: `channel factory init error` (rclpy + SDK no mesmo processo);
  nenhum comando chegou ao robô → `body_worker`.
- Emergência: com o robô em pé (FSM 801), `robo_emergencia.py` → damp confirmado (FSM 1).
- Rotina armada completa (sequência final, pausa 0,5 s): ~41 s do reconhecimento ao fim
  (sentido 1,3 s; continência 1,1 s; fala 5,1 s; desc arma 1,3 s; descansar 5,9 s; 15 s;
  à vontade 11 s). Inicialização (damp → em pé → equilíbrio): ~16 s.

## Independência do ~/hhhh (2026-11-03)

A rotina rodava importando o `G1ArmController` e as poses de `~/hhhh` e subindo o Piper pelo
`~/hhhh/start_tts_stt.sh`. Agora tudo vem do repositório:

- `g1_arm_controller.py`: cópia do controlador (sem tkinter; `[ipe-2-code]` marca as mudanças).
- `poses/`: as 13 poses que ele lê, instaladas em `share/robot_reaction_ros/poses`; o parâmetro
  `poses_dir` do body_node (no lugar de `hhhh_dir`) troca a pasta.
- `scripts/robo_voz.sh`: contêiner `ipe-piper` com a mesma imagem Docker, só o Piper, sem montar
  o `~/hhhh`. Reaproveita quem já responde na porta 5005.
- `tests/test_g1_poses.py` (CI): toda pose que o controlador lê está no repositório.

A alteração feita no `~/hhhh/iniciar_robo.sh` (o START não aborta mais sem áudio) está registrada
em `docs/hhhh/`. O movimento é o mesmo testado em 2026-10-30, mas a cópia ainda não rodou armada
no robô.
