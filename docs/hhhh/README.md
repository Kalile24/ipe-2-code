# O que este projeto tem do `~/hhhh`

`~/hhhh` é o projeto de voz e movimentos militares que divide o robô com o nosso: o botão START
do controle roda `~/hhhh/iniciar_robo.sh`, e os combos F1+… fazem as posturas pelo
`movimentos_militares.py`. Ele não está em git. A rotina de cumprimento usa o mesmo movimento, mas
**não depende mais da pasta `~/hhhh`**. Tudo o que ela usa foi copiado para cá em 2026-11-03:

| No `~/hhhh` | Aqui | Mudanças |
|---|---|---|
| `G1ArmController` em `g1_arm_calibration_gui_v29.py` | `ros2_ws/src/robot_reaction_ros/robot_reaction_ros/g1_arm_controller.py` | sem a GUI (tkinter); poses do pacote; espera do FSM 4 do item abaixo |
| `MovimentosMilitares.wait_fsm4_transition_complete` em `movimentos_militares.py` | o mesmo arquivo, no lugar da espera da v29 | nenhuma no comportamento |
| velocidades dos combos (F1+Y 0,7; F1+B 2,0; F1+A 1,4) | `body_worker.py` (`G1Body`) | nenhuma |
| `poses/*.json` (as 13 que o controlador lê) | `ros2_ws/src/robot_reaction_ros/poses/` | nenhuma |
| contêiner `openvoice-piper` (`start_tts_stt.sh`) | `scripts/robo_voz.sh` (contêiner `ipe-piper`) | mesma imagem Docker e API; só o Piper, sem Whisper e sem montar o `~/hhhh` |

O que continua vindo de fora do repositório, no robô: a imagem Docker
`openvoice-piper-whisper-jetson:1.0` (Piper e a voz `pt_BR-faber-medium`), o `unitree_sdk2py` e o
`pymodbus` no venv do projeto, e a caixa Bluetooth KD-833.

Duas consequências da cópia:

- Corrigir uma pose ou uma postura no `~/hhhh` **não** muda a nossa rotina. Copie de novo o arquivo
  (as mudanças nossas estão marcadas com `[ipe-2-code]`) e rode `tests/test_g1_poses.py`.
- O `scripts/robo_rotina_cumprimento.sh` ainda olha o `~/hhhh`, mas só para se recusar a rodar se
  o START estiver de pé (`movimentos_militares.py` ou `assistente.py`): seriam dois donos do braço
  e da caixa. Se o `~/hhhh` não existir, essa checagem passa e o resto funciona igual.

## Alteração feita no `~/hhhh`: `iniciar_robo.sh`

Em 2026-10-29 o `~/hhhh/iniciar_robo.sh` foi alterado no robô. O original ficou ao lado, em
`~/hhhh/iniciar_robo.sh.bak_20261029`. O diff está em [`iniciar_robo.sh.patch`](iniciar_robo.sh.patch).

Antes, o START abortava (`exit 1`) se faltasse o PulseAudio, a caixa Bluetooth, o contêiner de
voz, o Piper ou o Whisper. Nesse caso o `movimentos_militares.py` nem subia. Agora cada uma dessas
falhas vira um `AVISO` no `~/hhhh/inicializacao.log` e o START segue sem a parte que faltou. Os
movimentos funcionam mesmo sem áudio.

Para desfazer no robô:

```bash
cp ~/hhhh/iniciar_robo.sh.bak_20261029 ~/hhhh/iniciar_robo.sh
```

Para refazer a partir do original:

```bash
cd ~/hhhh && patch -p1 < ~/ipe-2-code/docs/hhhh/iniciar_robo.sh.patch
```
