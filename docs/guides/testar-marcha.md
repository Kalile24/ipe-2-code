# Testar a marcha — modos de caminhada do G1

Objetivo: um andar **mais militar** (aspecto de marcha, passo mais assentado) e **giros mais consistentes**. Aqui só se
testa pelo **controle da Unitree**, comparando os modos de caminhada que o firmware já tem; nenhum código nosso muda o
modo. Se um modo ficar melhor que o atual, o código passa a aceitá-lo depois (hoje a rotina só arma em **801**).

Fonte: documentação oficial do controle (`UNITREE_G1_base_documentacao/ORIGINAIS/unitree_official_G1_developer/228_remote_control.md`)
e dos modos (`255_sport_services_interface.md`).

## Trocar de modo é arriscado?

**Pelo controle, seguindo o procedimento da Unitree, o risco é baixo**: é o caminho previsto pelo fabricante e o robô
continua equilibrado. O risco está em três lugares:

1. **Passar por damping (L2+B) ou por agachar (L2+A) fora do suporte** — no damping os motores soltam e ele **cai**.
   Neste teste não se usa L2+B nem L2+A com o robô em pé fora do suporte. **L2+B é a parada de emergência**, só com o
   robô no suporte (ou se ele estiver caindo de qualquer jeito).
2. **Combinações apertadas pela metade** — em pé, algumas trocas só valem **seguradas por 2 s**; soltar antes pode deixar
   a troca pela metade. Siga os tempos abaixo.
3. **A nossa rotina num modo que ela não conhece** — já está protegida: fora do 801 o `body_node` **recusa armar e não dá
   damp** (F3+↑ toca os dois tons graves; o painel mostra a recusa). Mesmo assim, **pare a rotina (F3+↓) antes do teste**
   e volte ao 801 antes de subir de novo. Trocar o modo **pelo nosso código** (`SetFsmId`) seria mais arriscado: não faça.

## Antes de começar

- Bateria **≥ 50%** (painel, **Bateria**). Piso plano e firme, **3 m livres** à frente e atrás.
- **Rotina parada** (F3+↓; `tmux ls` sem a sessão `rotina`). Ninguém apertando START nem F1+… (são do `~/hhhh`).
- Uma pessoa **segurando por trás** (alça ou cinta), outra no **controle**, outra **filmando** de lado e de frente.
- Num terminal do robô, deixe rodando os dois leitores (só leitura, não mandam comando):

```bash
cd ~/ipe-2-code && source scripts/ambiente_robo.sh
python3 scripts/robo_ler_modo.py        # qual FSM_ID o robô está (mostra "<== MUDOU" a cada troca)
python3 scripts/robo_medir_giro.py      # em outra janela: quanto girou (para os giros)
```

## Como apertar os botões

- **"Segure A + clique B":** aperte e **mantenha** o primeiro botão (L1, L2, R1, R2 ou SELECT), **clique** o segundo e
  só então solte o primeiro.
- **Com o robô em pé, mantenha o primeiro botão por ~2 s** depois do clique (a Unitree avisa que, em pé, algumas trocas
  só valem seguradas por 2 s). Confira no `robo_ler_modo.py` que o FSM_ID mudou antes de mexer no joystick.
- **Duplo clique** (velocidade baixa/alta): dois toques rápidos, < 0,5 s entre eles.
- O LED do peito/cabeça muda de cor com o modo (laranja = damping, azul-escuro = espera, amarelo = depuração).

## Os modos

| Combo (em pé, segurar ~2 s) | Modo | FSM_ID esperado | O que tem |
|---|---|---|---|
| **R2 + A** | **Run Control** — o atual | **801** | Anda e corre. R2+↓ corrida lenta, R2+↑ corrida rápida. Segurar START + segurar ↑/↓: inclina o tronco à frente/atrás |
| **R1 + X** | **Main Operation Control** | provavelmente **500** (Walk) | Controlador **de caminhada**. Duplo clique **L2 = velocidade baixa**, duplo clique **L1 = alta**. **Compensação de deriva**: segurar R1 + clicar → (puxa à esquerda) / ← (à direita) / ↓ (à frente) / ↑ (atrás) |
| **R1 + Y** | Main Operation Control **para cintura de 3 eixos** | provavelmente **501** | O mesmo do R1+X usando a cintura. **A Unitree recomenda este modo para a cintura de 3 eixos** — a do nosso G1-EDU 29 DoF |

A relação R1+X → 500 e R1+Y → 501 é dedução pelos nomes: o `robo_ler_modo.py` confirma. No firmware 8.6 em diante o
801 pode aparecer como **802**.

**Altura do passo e do corpo (talvez):** a documentação traz, num trecho antigo, que no Run Control **B aumenta a altura
do passo**, **A diminui**, **Y sobe o corpo** e **X abaixa**. Passo mais alto = aspecto de marcha. Pode não existir no
firmware atual: teste **primeiro no suporte**, um clique por vez, olhando as pernas. Se mudar algo, volte ao normal
contando os cliques.

## Roteiro (repita para cada modo: 801, R1+X, R1+Y)

1. Em pé, no modo a testar (confirme o FSM_ID). Se for R1+X/R1+Y, teste também com **duplo clique em L2** (velocidade baixa).
2. **Marcha:** ~3 m à frente com o joystick todo à frente, parar, ~3 m de volta. Filme de lado (altura e cadência do
   passo) e de frente (balanço lateral).
3. **Giros:** zere o `robo_medir_giro.py` (Ctrl+C e rode de novo) e faça **3 meias-voltas** com o joystick de giro todo
   para um lado, parando quando achar que deu 180°. Anote o `girado` de cada uma. Depois 3 para o outro lado.
4. **Parado:** 20 s em pé sem mexer. Ele fica firme? Dá passos à toa?
5. Volte ao **801 (R2+A, segurar ~2 s)** antes de terminar ou de subir a nossa rotina.

## Anote

| Modo (FSM_ID) | Velocidade | Marcha: parece militar? (1–5) | Balanço lateral (1–5) | Giros (° de cada uma) | Parado firme? | Observações |
|---|---|---|---|---|---|---|
| 801 | normal | | | | | |
| R1+X ( ) | normal | | | | | |
| R1+X ( ) | baixa | | | | | |
| R1+Y ( ) | normal | | | | | |
| R1+Y ( ) | baixa | | | | | |

**Giros consistentes:** a nossa meia-volta já fecha pelo IMU (para a 3° de 180°, em qualquer modo). Os giros pelo joystick
mostram o quanto cada modo "escorrega" no giro — quanto menor a diferença entre as 3 medidas, melhor.

## Depois do teste

Mande a tabela e os vídeos. Se R1+X ou R1+Y ficar melhor, o próximo passo é o código aceitar esse FSM_ID para armar (com
teste no suporte primeiro). As posturas de braço (`arm_sdk`) só valem em "travado em pé" e nos "controles de movimento"
da Unitree: isso também se testa no suporte antes de usar o modo novo na rotina.
