# Retorno ao ponto de partida, escuta contínua de voz e painel completo — Design

Data: 2026-11-10. Contexto: continua a meia-volta (`2026-11-07-meia-volta-design.md`), os comandos de voz
(`2026-11-07-comandos-de-voz-design.md`, agora com Vosk) e o painel (`2026-11-04-painel-design.md`).
Status: **implementado em 2026-11-10** (retorno, escuta contínua, painel, fala de apresentação e cadastro pela
webcam); o retorno ainda não andou no robô (falta a medição da odometria, guia `teste-no-robo.md` 9a).

## Decisões do usuário (2026-11-10)

- Depois do cumprimento o robô faz, **sem comando**: desfaz a continência, fica à vontade, **gira 180°** (a
  meia-volta que já existe), **anda até a posição de onde saiu** antes de aproximar, **gira 180° de novo** para
  ficar de frente para a pessoa e **para**.
- Volta **de frente** (gira e anda para a frente), não de ré.
- "Voltar à posição original": a melhor solução fica a critério do Claude (abaixo).
- **Escuta contínua de voz**, ligada e desligada pelo **controle** e pelo **painel**, **com sinal** de que está ouvindo.
- O painel passa a operar tudo: estágios (incluindo o retorno), escuta contínua, ordens de voz e os ajustes novos.

## A. Retorno ao ponto de partida

### Como "voltar ao lugar" (escolha do Claude)

**Odometria do próprio robô** (`rt/lf/odommodestate`, 20 Hz, tipo `SportModeState_`: `position[0..1]` em m no
referencial do mundo e `imu_state.rpy[2]`), lida pelo `body_worker`, que já tem o `LocoClient` e o `low_state`.

- **Ao começar a rotina** (antes de virar/aproximar), o `body_worker` grava o **ponto de partida** `P0 = (x, y)` e o
  **rumo para a pessoa** `ψ_pessoa` (o yaw quando terminou de virar para ela).
- **Volta em malha fechada**, não por tempo: depois da meia-volta, anda com `vx` constante e corrige o rumo para `P0`
  (`vyaw = kp × erro de rumo`, com teto), até a distância a `P0` ficar abaixo de `tolerancia_retorno_m` (0,15 m).
- **Segundo giro com alvo absoluto**: gira até o yaw chegar a `ψ_pessoa` (não "mais 180°"). Assim os erros do primeiro
  giro e da caminhada não se acumulam: ele termina de frente para onde a pessoa estava.
- **Sem aproximação** (ele não andou, ou andou < `retorno_min_m`, 0,3 m): não há para onde voltar. Pula a caminhada e
  o segundo giro; fica como hoje, de costas e esperando o operador.

Alternativas descartadas: **tempo × velocidade** (a aproximação muda a velocidade no caminho e corrige o rumo, então
não dá para "desandar" com precisão) e **voltar pela câmera** (a pessoa fica atrás do robô na volta).

### Passo zero: medir a odometria (só leitura, como o `robo_medir_giro.py`)

`scripts/robo_medir_odometria.py` mostra `x`, `y`, `yaw` e a distância desde o início, sem mandar comando. Pelo
controle da Unitree: andar ~1 m para a frente e voltar. Confere: o tópico existe (precisa do State Estimator ≥ 1.0.0.1),
1 m andado lê 0,9–1,1 m, e voltar ao ponto lê < 0,15 m. **Se a odometria não existir ou for ruim, o retorno não é
implementado assim**: a decisão volta para o usuário (ex.: retorno por tempo, aceitando o erro).

### Segurança

- Caminhada **cega** (sem detecção de obstáculo), como o passo de hoje: o operador garante o caminho livre. Teto de
  distância: no máximo a distância da aproximação + 0,5 m; passou disso, para e falha.
- **Afastando em vez de aproximar** (distância a `P0` aumentando por 1 s seguido), **odometria parada** (sem leitura
  há 0,5 s), **tempo-limite** (`tempo_max_retorno_s`): para (`StopMove`) e registra `retorno: falhou (<motivo>)`.
- **PARAR, F3+↓ e Ctrl+C** interrompem na hora, como a meia-volta.
- Só armado e em FSM 801. Desarmado: `dry_run retorno` no log.

### Estágio e ajustes

- Estágio novo **`retorno`**, depois de `meia_volta` (só roda se a meia-volta deu certo). Com o retorno ligado, o passo
  cego da meia-volta (`passo_m`) não é dado.
- Novos campos no `operacao.yaml`, com faixa em `LIMITES_OPERACAO` e no painel:

  | Campo | Padrão | Faixa |
  |---|---|---|
  | `vx_retorno` (m/s) | 0,3 | 0,1 a 0,5 |
  | `tolerancia_retorno_m` | 0,15 | 0,05 a 0,4 |
  | `retorno_min_m` | 0,3 | 0 a 1 |
  | `tempo_max_retorno_s` | 30 | 5 a 60 |

- Status: `retorno: andando (faltam 1.2 m)`, `retorno: virando para a pessoa`, `retorno: fim`.

## B. Escuta contínua de voz

- Modo do `voz_node`, **desligado ao subir**. Ligado, um `arecord` contínuo alimenta o Vosk em fluxo; cada frase
  reconhecida segue o mesmo caminho de hoje (`reconhecer` → rotina de voz).
- **Exige o vocativo:** na escuta contínua a gramática só tem `tenente <comando>` e `tenente [unk] <comando>` (mais
  `[unk]`). "Sentido" solto, vindo da plateia, não dispara. O apertar-e-falar (F3+Y) continua aceitando sem vocativo.
- **Não ouve a si mesmo:** descarta o áudio enquanto o robô fala (o Piper responde só depois de tocar) e por mais
  0,5 s depois.
- **Liga e desliga:** combo **F3+L1** (livre hoje) e botão **Escuta contínua** no painel. Com a escuta ligada, o F3+Y
  continua funcionando (pausa a escuta durante o aperto).
- **Sinal:** ao ligar, dois bipes subindo e a fala "Escuta ligada"; ao desligar, dois bipes descendo e "Escuta
  desligada". O painel mostra **ESCUTANDO** em destaque e a última frase ouvida.
- PARAR (F3+↓, painel, Ctrl+C) desliga a escuta.

## C. Painel para operar tudo

Na aba **Operar**:
- **Estágios ao vivo** (já existe): + **Retorno**.
- **Escuta contínua**: botão liga/desliga, estado (ESCUTANDO / desligada) e a última frase ouvida, com o comando entendido.
- **Ordens** (já existe): + **Atenção** e **Fala de apresentação** (F3+R1, feito em 2026-11-10).
- **Retorno**: distância ao ponto de partida durante a volta e o resultado (fim / falhou e por quê).

Na aba **Calibrar**: grupo **Retorno** com os campos novos.

## Fora deste design

- Desviar de obstáculos na volta.
- Voltar a procurar a pessoa (girar até achar o rosto) se ela tiver saído do lugar.
- Escuta contínua sem vocativo.

## Ordem de implementação

1. `robo_medir_odometria.py` e **medição no robô** (decide se o retorno segue este design).
2. Retorno: `core/retorno.py` (puro: rumo, distância, decisões de parada, com testes), ordem `retorno` no `body_worker`,
   estágio, ajustes e status.
3. Escuta contínua: `core` (gramática com vocativo obrigatório, descarte enquanto fala), `voz_node`, combo F3+L1, bipes.
4. Painel: retorno, escuta contínua, ordens novas, ajustes.
5. Guias (`operar-o-robo.md`, `teste-no-robo.md`) e teste no robô, na ordem: odometria → retorno no suporte desarmado
   → retorno armado com espaço → escuta contínua.
