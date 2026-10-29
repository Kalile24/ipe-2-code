# Rotina de cumprimento: posturas militares + fala — Design

Data: 2026-10-29. Continua a Fase 2 (`2026-10-21-robot-reaction-design.md`).

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

- **Reaproveitar o `G1ArmController` do `~/hhhh` sem editá-lo** (import por `sys.path`), com as
  mesmas velocidades e a espera do FSM 4 do `movimentos_militares.py`. Gestos do firmware não
  fazem sentido/descansar. O `movimentos_militares.py` não sobe junto (um dono do braço).
- **`body_node`**: único dono do braço e da voz. Desarmado por padrão (fala, posturas no log);
  `armed` só na partida, e armar inicializa o robô (damp → em pé → equilíbrio, no suporte).
  Ctrl+C espera o passo atual e devolve os braços.
- **YAML**: cada pessoa tem `gesto` (firmware, `gesture_node`) ou `passos` (`postura`/`fala`/`pausa`).
  Rotina que mexe o braço tem que terminar a última postura em `a_vontade`.
- **Repetição**: a mesma pessoa só de novo depois de 5 min **e** de ter saído da frente por 5 s
  seguidos (ficar parado na frente nunca repete; rosto virado não conta como saída). Comando
  manual de teste: `ros2 param set /reaction_node liberar <nome|todos>`
  (`scripts/robo_liberar_cumprimento.sh`).
- **Fala que falha não para o movimento; postura que falha encerra e tenta `a_vontade`.**
- **Processo à parte para o braço**: rclpy e o SDK da Unitree no mesmo processo falham
  (`channel factory init error`, CycloneDDS com duas configurações). O body_node abre o
  `body_worker` (sem ROS), dono do G1ArmController. O mesmo vale para o gesture_node, nunca armado.
- **Emergência pelo computador** (`scripts/robo_emergencia.py`): damp e mata o worker; testado
  com o robô em pé no suporte em 2026-10-30.
- **Nome escrito como soa**: "Nichinica" (o Piper lê "Nixinica" como "ksi").
