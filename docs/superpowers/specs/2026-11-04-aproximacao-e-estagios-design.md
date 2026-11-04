# Aproximação da pessoa, estágios e partida pelo controle — Design

Data: 2026-11-04. Contexto: continua a rotina de cumprimento
(`2026-10-29-rotina-cumprimento-design.md`, revisada em 2026-11-04: ação `/reaction/rotina`,
body_node + body_worker). Depois desta vem a interface web de monitoramento (passo 3).

Objetivo: ao reconhecer uma pessoa do mapa, o robô **se vira para ela, anda até ela e então faz a
rotina** (sentido, continência, fala...). O operador escolhe quais **estágios** rodam (só falar, só
saudar, virar + falar + saudar...) e pode **subir tudo pelo terminal ou por um combo no controle**,
para a operação completa do robô na demonstração.

## Decisões do usuário (2026-11-04)

- Na demonstração o robô está **fora do suporte, livre para andar**, com alguém segurando o
  controle.
- **Estágios escolhíveis**, em qualquer combinação (ex.: só saudar, só falar, virar + falar + saudar).
- **Partida pelo terminal ou por um botão do controle**, com um **combo diferente** do START do
  `~/hhhh` (os dois projetos continuam funcionando).
- **Pelo botão, sempre armado**: é a opção de operação completa do robô.
- **Valores (distância, velocidades, tempos) configuráveis**; a interface do passo 3 vai mexer
  neles. O usuário não sabe ainda os números certos: começa com padrões e ajusta no teste.
- **A rotina do Gil não muda** (regra em `CLAUDE.md`): sentido → continência → "Olá, aspirante a
  oficial da reserva Gil, sou o Tenente Nichinica" → desc_arma → descansar → 15 s → à vontade.
- Os scripts continuam `.sh` (não um launch só).

## Fatos

- Detecções: `/face_recognition/detections` (`vision_msgs/Detection2DArray`, Foxy). Por rosto:
  `bbox.center.x/y`, `bbox.size_x/size_y` em pixels da imagem e `results[0].id` = nome (ou
  `desconhecido`). ~20 detecções/s com a webcam USB da cabeça em 640x480 (TensorRT).
- O campo de visão da webcam USB não está medido.
- O `body_worker` já tem o `LocoClient` do SDK (`self.robot.loco`, usado no `SetVelocity` do
  descansar e no `StopMove`). `SetVelocity(vx, vy, vyaw, duração)`: a duração faz o robô parar
  sozinho quando ela acaba.
- A inicialização armada já aproveita o robô em equilíbrio (FSM 801) sem passar pelo damp e recusa
  qualquer outro modo em pé (`G1Body.initialize`).
- O `~/hhhh` tem o `unitree-start-joystick.service` (boot) que lê o controle e roda
  `~/hhhh/iniciar_robo.sh` no START; os combos F1+… são do `movimentos_militares.py`. O firmware usa
  combos com L1/L2/R1/R2. Teclas no campo `keys` do `rt/wirelesscontroller` (o `~/hhhh` usa R2 =
  `0x10`, A = `0x100`).

## Comportamento

### Estágios

Quatro, ligados ou desligados independentemente: **`virar`**, **`aproximar`**, **`fala`**,
**`posturas`**. Padrão: todos ligados.

- O `reactions.yaml` não muda: os estágios **filtram** a rotina na hora de executar.
  - `posturas` desligado: tira os passos `postura` **e** os `pausa` (a pausa é parte da postura;
    "só falar" não fica 15 s parado em silêncio). Sem postura nenhuma, o robô não pega o arm_sdk.
  - `fala` desligado: tira os passos `fala`.
  - Se sobrar uma rotina sem posturas, nada mais muda (a regra de terminar em `a_vontade` só vale
    quando há posturas, e o filtro tira todas).
- `aproximar` inclui virar (para andar até a pessoa o robô tem que estar de frente).
- `virar` sem `aproximar`: só gira no lugar até centralizar a pessoa.
- Ordem: virar/aproximar primeiro, depois a rotina filtrada.
- Desarmado: o robô não se mexe, então virar/aproximar nunca terminariam. **Decisão minha
  (builder):** desarmado, virar/aproximar só medem e registram por ~2 s (erro de direção, distância
  estimada e as velocidades que mandaria) e dão o estágio como feito; a rotina segue normal, com as
  posturas só no log e a fala de verdade. Assim o modo de teste continua útil e serve para
  calibrar `campo_horizontal_graus` e `altura_rosto_m` sem o robô andar.

### Virar e aproximar (a partir da caixa do rosto)

A pessoa alvo é a que o `reaction_node` mandou cumprimentar; o body_node segue as detecções com
esse nome (se houver mais de uma caixa com o nome, a maior). Laço a ~10 Hz:

- **Erro de direção:** `erro = (center.x − largura/2) / largura × campo_horizontal`. Rosto à
  direita da imagem → virar para a direita. O sinal fica num parâmetro (`inverter_giro`) para
  corrigir no teste, sem mexer no código.
- **Distância estimada:** `d = f × altura_rosto_m / size_y`, com
  `f = (largura/2) / tan(campo_horizontal/2)`. `altura_rosto_m` é calibração (padrão 0,20 m).
- **Comando:** `vyaw = clamp(kp_giro × erro, ±vyaw_max)`; anda para frente só quando
  `|erro| < angulo_para_andar`, com `vx = clamp(kp_avanco × (d − distancia_alvo_m), 0, vx_max)`.
  Nunca anda para trás nem para os lados (`vy = 0`). Pronto quando `|erro| < angulo_ok` e
  (sem `aproximar`, ou `d ≤ distancia_alvo_m`).
- Cada comando vai com `SetVelocity(..., duração = 0,5 s)`: se o nosso processo morrer, o robô para
  em meio segundo. No fim de cada caso (pronto, desistiu, cancelado) manda parar (velocidade zero).
- **Para e não cumprimenta** quando: o rosto some por mais que `perda_rosto_s` → para; se não voltar
  em `desistir_s`, desiste. Também desiste em `tempo_max_s`. Cancelamento da ação ou Ctrl+C: para
  na hora (sem esperar o passo, ao contrário das posturas).
- Desistir conta como cumprimento falhou, igual a uma rotina que falhou (não fica tentando de novo
  a cada frame).

### Parâmetros (padrões são chute, para ajustar no robô)

| Parâmetro | Padrão | O que é |
|---|---|---|
| `estagios` | `virar,aproximar,fala,posturas` | quais estágios rodam |
| `campo_horizontal_graus` | 60 | campo de visão horizontal da webcam (medir) |
| `largura_imagem` | 640 | largura em pixels da imagem das detecções |
| `altura_rosto_m` | 0,20 | altura real da caixa do rosto (calibração da distância) |
| `inverter_giro` | false | troca o sinal do giro se ele for para o lado errado |
| `distancia_alvo_m` | 1,2 | para de andar a esta distância |
| `angulo_ok_graus` | 5 | erro de direção aceito como "de frente" |
| `angulo_para_andar_graus` | 15 | só anda para frente com erro menor que este |
| `vyaw_max` | 0,3 rad/s | giro máximo |
| `vx_max` | 0,2 m/s | velocidade máxima para frente |
| `kp_giro`, `kp_avanco` | 1,0 ; 0,5 | ganhos |
| `perda_rosto_s` | 1,0 | rosto sumido por isso → para |
| `desistir_s` | 5,0 | rosto sumido por isso → desiste |
| `tempo_max_s` | 20 | aproximação mais longa que isso → desiste |

Ficam num arquivo de parâmetros ROS do body_node, `config/operacao.yaml` (padrões no pacote);
o launch aceita outro arquivo (`operacao_file`). A interface do passo 3 vai escrever esse arquivo.
`robo_rotina_cumprimento.sh --estagios virar,fala` sobrescreve só os estágios.

### Partida pelo controle

- Um programa nosso, **sem ROS**, lê o controle pelo SDK da Unitree (`rt/wirelesscontroller`) por
  callback (sem laço ocupado; o do `~/hhhh` gasta ~80% de um núcleo).
- **F2 + UP** sobe a rotina **armada**, com os parâmetros salvos (`operacao.yaml`); **F2 + DOWN** é
  a parada (ver "Parada de emergência com o robô solto"). Os dois combos são configuráveis. Disparo na borda (apertou), não enquanto segura; um segundo F2+UP com a rotina
  de pé não faz nada.
- **Pelo controle, só com o robô em equilíbrio (FSM 801)** (decisão do usuário, 2026-11-04): o
  operador põe o robô em pé pelo controle e então aperta F2+UP. Robô mole (FSM 0/1) ou em outro
  modo: recusa, sem nunca rodar o damp → em pé. Não há terminal olhando, então a recusa é **falada
  pela caixa** (ex.: "não estou em equilíbrio, não vou começar") e registrada no log. Isso pede um
  modo "só 801" na inicialização (hoje ela aceita FSM 0/1 com damp, que continua valendo só pelo
  script com a pergunta "está no suporte?"). O script ganha uma opção não interativa que usa esse
  modo "só 801"; é ela que o programa do controle chama.
- Mesmas recusas do script: não sobe se o START do `~/hhhh` estiver de pé; não sobe duas vezes.
- Para estar pronto no combo, o programa sobe no boot como serviço (como o do `~/hhhh`). **Instalar
  um serviço no robô compartilhado: combinar antes com quem usa o robô.** O repositório traz a unit
  e o passo do guia; quem instala é o operador.

### Parada de emergência com o robô solto

Decisão do usuário (2026-11-04): **F2 + DOWN para de andar na hora** — velocidade zero
imediatamente, sem esperar nada, e cancela o cumprimento; uma postura do braço já em movimento
termina e os braços voltam (`a_vontade`). O robô fica em pé, em equilíbrio. Encerra a rotina
(como o Ctrl+C) depois disso.

- O "parar de andar" não pode esperar na fila de uma postura: tem que chegar ao `LocoClient` mesmo
  com uma ordem de postura em andamento no body_worker.
- O `robo_emergencia.py` (damp) continua, mas **só no suporte**: fora do suporte o damp derruba o
  robô. O guia e a janela `emergencia` passam a dizer isso. Pelo controle não se abre a janela de
  emergência; a parada é o F2+DOWN e os modos do próprio controle da Unitree.

## Antimetas

- Andar até alguém que não está no mapa (`desconhecido` ou fora do `reactions.yaml`).
- Andar para trás, de lado, ou mais rápido que `vx_max` / `vyaw_max`.
- Mexer o robô desarmado (só log).
- Continuar andando sem detecção nova (o comando expira em 0,5 s).
- Mudar a rotina do Gil, o serviço ou os combos do `~/hhhh`.
- Desviar de obstáculos: não há; o operador está com o controle (F2+DOWN e os modos da Unitree).
- Rodar o damp → em pé a partir do controle.

## Fora do escopo

- A interface web (passo 3); ela só vai ler o status e escrever o `operacao.yaml`.
- Wi-Fi do robô como ponto de acesso (passo 3).
- Medir distância com profundidade (D435i): a webcam é só 2D.

## Para quem vai construir

- Onde fica o laço de controle (body_node, que já recebe ROS) e como a velocidade chega ao
  body_worker (nova ordem no protocolo JSON, com `id`), desde que um comando de velocidade nunca
  espere uma postura em andamento e o "parar" passe na frente.
- Formato do resultado/feedback da ação para a aproximação (o status em `/reaction/rotina_status`
  tem que dizer o estágio e a distância estimada; a interface do passo 3 vai ler).
- Nome e lugar do programa do controle e da unit systemd; como ele encerra a rotina (ex.: Ctrl+C
  na janela `rotina` do tmux).
- Testes: o laço de controle em `core/` puro (erro → vyaw/vx, desistências) com dublês; o filtro
  de estágios também.
