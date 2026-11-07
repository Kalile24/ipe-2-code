# Meia-volta volver depois do cumprimento — Design

Data: 2026-11-07. Contexto: continua a aproximação e os estágios
(`2026-11-04-aproximacao-e-estagios-design.md`) e a rotina de cumprimento
(`2026-10-29-rotina-cumprimento-design.md`).

Objetivo: depois de cumprimentar, o robô **faz meia-volta pela esquerda e dá um passo à frente**,
como um romper marcha. É o fecho militar do cumprimento na demonstração.

## Decisões do usuário (2026-11-07)

- A meia-volta acontece **logo depois do `a_vontade`**, sem pausa.
- O giro é **pela esquerda**, 180°.
- Depois do giro, **um passo à frente de ~0,2 m**, e o robô para.
- **A rotina é igual para qualquer pessoa** por enquanto. A regra que impedia mudar a rotina do Gil
  saiu do `CLAUDE.md`.
- **Fica para depois** (outro design): voltar ao local de partida e se virar de novo para a pessoa.
  Depois disso vem o Whisper com comandos de voz que disparam respostas físicas pré-definidas
  (sentido, apresentação, continência).

## Comportamento

1. A rotina termina com sucesso (todos os passos, até o `a_vontade`).
2. Se o estágio `meia_volta` está ligado, o robô gira pela esquerda até o ângulo de giro medido
   chegar a 180° (com tolerância) e para.
3. Anda ~0,2 m para a frente em velocidade baixa e para.
4. Fica parado, de costas para a pessoa, **esperando o operador**: não dispara outra rotina sozinho,
   mesmo reconhecendo alguém (provavelmente da plateia, atrás dele). Volta a cumprimentar quando o
   operador libera, no botão **Liberar cumprimentos** do painel (já existe) ou num combo do controle.
   Escolha do Claude, a confirmar com o usuário: sem isso, 10 s depois ele andaria até o próximo
   rosto reconhecido. A espera só começa depois de uma meia-volta feita; com o estágio desligado,
   tudo segue como hoje.

**Quando não acontece:** a rotina falhou ou foi interrompida, a aproximação desistiu, PARAR/Ctrl+C,
ou o estágio está desligado. Nesses casos, nada de giro nem passo.

**Desarmado ou não inicializado:** não se move; só registra no log o que faria
(`dry_run meia_volta`), como as posturas fazem hoje.

## Decisões de implementação (escolhas do Claude, o usuário pode mudar)

- **Estágio novo, não passo no YAML.** `meia_volta` entra em `core/stages.ESTAGIOS`, roda depois da
  rotina e vale para todas as pessoas, inclusive as que o painel já gravou em `data/reactions.yaml`
  no robô, sem editar nenhum mapa. O painel ganha a caixa "Meia-volta" junto das outras, e o
  `config/operacao.yaml` passa a ter `estagios: "virar,aproximar,fala,posturas,meia_volta"`.
  Motivo: "igual para qualquer pessoa" e desligável na hora pelo operador, como os outros movimentos.
- **Ajustes já salvos no robô.** O painel grava `data/operacao.yaml`, que sobrescreve o padrão do
  pacote; num robô com ajustes salvos, `estagios` não teria `meia_volta`. Uma lista de estágios salva
  antes de o estágio existir ganha `meia_volta` ao carregar (uma vez; se o operador desmarcar depois,
  fica desmarcado). Escolha do Claude, a confirmar com o usuário.
- **Ângulo medido, não tempo.** O giro fecha no yaw do IMU (`rt/lowstate`, `imu_state.rpy[2]`), que o
  `G1ArmController` já assina (`low_state`). A odometria (`rt/odommodestate`) só entra se o IMU se
  mostrar ruim na medição. O laço trata a virada de ±π.
- **O laço roda no `body_worker`**, que tem o `LocoClient` e o `low_state`. Ordem nova, por exemplo
  `{"cmd": "meia_volta", "graus": 180, "passo_m": 0.2}`, atendida pela thread executora. O `parar`,
  que a thread de leitura atende na hora, precisa **interromper o laço** (hoje só chama `StopMove`, e
  o laço voltaria a mandar velocidade). Ao sair por qualquer motivo, `StopMove`.
- **O passo** é andar `vx` baixo até a distância chegar a 0,2 m. Se a odometria não der posição
  confiável, vira tempo × velocidade (0,2 m a 0,2 m/s ≈ 1 s) e isso fica registrado no código.
- **Parâmetros novos no `operacao.yaml`**, com faixa em `LIMITES_OPERACAO` e no painel:

  | Campo | Padrão | Faixa |
  |---|---|---|
  | `vyaw_meia_volta` (rad/s) | 0,5 | 0,3 a 0,8 (0,22 não girou o robô) |
  | `tolerancia_meia_volta_graus` | 10 | 2 a 30 |
  | `passo_m` | 0,2 | 0 a 0,5 (0 = sem passo) |
  | `vx_passo` (m/s) | 0,2 | 0,05 a 0,3 |
  | `tempo_max_meia_volta_s` | 12 | 5 a 30 |

- **Sentido do giro:** esquerda = `vyaw` positivo (convenção do SDK). A medição confirma; se o yaw do
  IMU andar ao contrário do esperado nos primeiros instantes, o robô para e a meia-volta falha (não
  gira "até achar"). O `inverter_giro` do painel é da aproximação e não se aplica aqui.

## Segurança

- Só move armado e inicializado (FSM 801), como a aproximação.
- **PARAR**, o controle (F3+↓) e o Ctrl+C interrompem o giro e o passo na hora.
- **Tempo-limite**: sem chegar aos 180° em `tempo_max_meia_volta_s`, para e registra falha.
- **Ângulo ausente** (sem `low_state` ou valor não finito): não gira.
- Os mesmos tetos de velocidade do `body_worker` (`VX_MAX`, `VYAW_MAX`).
- O passo é às cegas (sem LiDAR). É curto e vai pelo caminho de onde o robô veio, mas o operador
  fica perto. A parada por LiDAR/D435i é pré-requisito da volta ao posto, não deste passo.

## Painel e log

- No log e no feedback da ação: `meia_volta: girando (yaw=+93°)`, `meia_volta: passo`,
  `meia_volta: fim` / `meia_volta: falhou (tempo)`.
- O painel mostra "fazendo meia-volta" no estado da rotina, como já faz com "virando" e "aproximando".

## Passo zero: medição no robô (antes do código de controle)

Com o robô em pé e armado pelo operador, ler `rt/lowstate` a uns 20 Hz enquanto ele gira pelo
controle, para a esquerda e para a direita:

- `imu_state.rpy[2]` muda ~180° numa meia-volta feita à mão? Qual o sinal ao girar para a esquerda?
- Deriva parado em 30 s (precisa ser bem menor que a tolerância).
- De quebra, `rt/odommodestate`: tem posição e yaw coerentes? (decide como medir o passo).

Script só de leitura, rodado pelo usuário ou com autorização dele (o robô é compartilhado).

## Testes

- Puros: o laço de giro com IMU de mentira (chega a 180°, tempo-limite, sentido errado, virada de ±π,
  ângulo ausente, interrupção) e o estágio novo em `parse_stages` / `filter_steps`.
- ROS: o `body_node` só pede a meia-volta depois de rotina com sucesso e com o estágio ligado.
- No robô: o roteiro de `docs/guides/teste-no-robo.md` ganha a meia-volta; o guia de operação
  (`docs/guides/operar-o-robo.md`) explica o estágio novo.

## Fora do escopo

Voltar ao local de partida, se virar de novo para a pessoa, desvio de obstáculos, giro por outro
ângulo além de 180°, meia-volta como passo do YAML.
