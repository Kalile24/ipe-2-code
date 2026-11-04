# Operar o robô: guia completo

Tudo o que é preciso para usar o G1: atualizar, ligar, operar pelo controle e pelo celular, cadastrar
pessoas, trocar webcam ou caixa, e resolver problemas.

> **Fora do suporte, nunca dê damp (F2+B): os motores soltam e o robô cai.**
> Para parar fora do suporte: **F2+↓** ou o botão **PARAR** do painel.

**Sempre:** alguém com o controle na mão e espaço livre em volta. Ninguém aperta START nem F1+… (são
do `~/hhhh`).

## 1. Atualizar o robô (uma vez)

Pelo cabo: `ssh unitree@192.168.123.164`.

```bash
cd ~/ipe-2-code && git status      # não pode haver alteração local; se houver, resolva antes
git fetch --prune origin && git switch master && git pull
source scripts/ambiente_robo.sh
cd ros2_ws && python3 -m colcon build --symlink-install    # tem que terminar com "3 packages finished"
cat ~/ipe-2-code/data/operacao.yaml; rm -f ~/ipe-2-code/data/operacao.yaml    # tira ajustes antigos, que venceriam os novos
```

Instalar ou reiniciar os serviços (se ainda não existem, combine antes com quem usa o robô):

```bash
mkdir -p ~/.config/systemd/user
cp ~/ipe-2-code/scripts/systemd/ipe-controle.service ~/ipe-2-code/scripts/systemd/ipe-painel.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ipe-controle ipe-painel
systemctl --user restart ipe-controle ipe-painel
sudo loginctl enable-linger unitree
```

Hotspot. **Enquanto ligado, o robô sai do Wi-Fi em que estava e a transmissão da D435i do `~/cesar`
para:** combine antes. O cabo continua funcionando.

```bash
~/ipe-2-code/scripts/robo_hotspot.sh liga        # cria e liga a rede IPE-G1
~/ipe-2-code/scripts/robo_hotspot.sh boot-liga   # opcional: liga sozinho a cada boot
```

Depois: `robo_hotspot.sh estado`, `desliga` (volta ao Wi-Fi anterior) ou `boot-desliga`.

### Se a versão nova der problema: voltar ao último teste físico

```bash
cd ~/ipe-2-code && git fetch origin && git switch backup/robo-ultimo-teste-fisico
source scripts/ambiente_robo.sh && cd ros2_ws && python3 -m colcon build --symlink-install
systemctl --user restart ipe-controle ipe-painel
```

Para retornar: `git switch master`, compile e reinicie do mesmo jeito. Fotos e ajustes em `data/` não
são afetados. Essa versão não tem o aviso de voz, a rotina do Aderson nem os recursos novos do painel.

## 2. Ligar e conectar

1. Webcam ligada no USB **antes** de subir a rotina. Caixa de som ligada (sem ela, o robô funciona sem fala nem bipes).
2. No celular, entre na rede **`IPE-G1`**, senha **`ipe-g1-2026`**. Se avisar que não há internet, continue conectado.
3. Abra **`http://10.42.0.1:8080`**. A faixa no topo diz se está tudo pronto ou o que falta.

Pôr o robô em equilíbrio (FSM 801): pelo controle da Unitree, ou, **no suporte e em damp**, segurando **F2+A** por 1,5 s.

## 3. Controle

O botão **F2** vem escrito **F3** em alguns controles. Segure F2 e aperte o outro botão.

| Combo | O que faz | Bipe |
|---|---|---|
| **F2 + ↑** | Sobe a rotina armada, com o automático **desligado**. Só em equilíbrio | dois tons subindo |
| **F2 + →** | Cumprimenta agora quem está sendo reconhecido | um tom |
| **F2 + ←** | Liga/desliga o automático (o robô fala o estado) | dois tons iguais |
| **F2 + ↓** | **Para:** velocidade zero, braços de volta, encerra. Também aborta um F2+A | tom grave; dois descendo ao encerrar |
| **F2 + A** (segurar 1,5 s) | Levanta **no suporte**. Só com o robô mole | três bipes curtos ao começar |
| **F2 + B** (segurar 1,5 s) | **Damp. Só no suporte.** Recusado com a rotina de pé | três curtos; três descendo |

**Dois tons graves = recusado:** nada aconteceu. O L2+B da Unitree não dá damp no modo de equilíbrio.

### Uso normal

1. Com o robô em equilíbrio, **F2+↑**. Em cerca de 1 min, o painel mostra o reconhecimento no ar.
2. **Manual:** pessoa na frente, **F2+→**. **Automático:** **F2+←** uma vez.
3. O robô vira, anda até a pessoa, para e faz o gesto: sentido → continência → fala → desc. arma → à vontade.
4. Ao terminar, **F2+↓**. Espere os dois tons descendo antes de subir de novo.

## 4. Painel

| Parte | Para que serve |
|---|---|
| **PARAR** (sempre visível) | Igual ao F2+↓ |
| **Faixa do topo** | Tudo pronto, ou o que está faltando |
| **Robô** | Estágio, armado, automático, webcam (nome e quedas), caixa, reconhecimento |
| **Na frente agora** | Quem está sendo visto, a nota e a altura da caixa do rosto (px) |
| **Comandos** | Subir desarmado (não se mexe; automático ligado), Subir armado (igual ao F2+↑), Cumprimentar agora, Liga/desliga automático, Liberar cumprimentos |
| **Últimos eventos** | O que o robô fez, com a hora. É o primeiro lugar a olhar quando algo falha |
| **Operação** | Ajustes (seção 7). Valem na próxima subida. **Restaurar padrões** desfaz tudo |
| **Pessoas** | Quem tem foto e rotina; **Remover** |
| **Adicionar pessoa ou trocar foto** | Seção 5 |
| **Caixa de som** | Testar som e trocar de caixa (seção 6) |

## 5. Pessoas

**Trocar a foto (deixar só uma por pessoa):** com a rotina de pé (**Subir desarmado** basta), em
**Adicionar pessoa ou trocar foto**, digite o nome, escolha a foto e salve. **As fotos anteriores da
pessoa são substituídas**, e ela já é reconhecida na hora.

**Pessoa nova:** digite o nome (minúsculas, sem espaço), o **tratamento** e a foto. Ela ganha o gesto
padrão e a fala *"Olá, <tratamento> <Nome>, sou o Tenente Nichinica"*. A rotina vale na **próxima subida**.
Se o nome soar mal, preencha **Nome falado** como ele deve soar.

**Coronel Aderson:** já tem rotina (*"Olá, coronel veterano Aderson, sou o Tenente Nichinica"*). Basta
cadastrar a foto com o nome `aderson`.

**Remover alguém:** primeiro pare a rotina, depois **Remover** na lista. As fotos são apagadas. Para
gil, marcos, bianco e aderson, a rotina continua no projeto e pode receber foto nova.

**Sobre usar uma só foto:** com uma foto, a nota varia muito com o ângulo (0,27 a 0,44 de cima contra
0,62 de frente, medido no robô). Use uma foto **de frente, com boa luz e, de preferência, feita na
altura e no lugar em que a webcam vai ver a pessoa**. Se alguém não for reconhecido, acrescente mais
fotos dessa pessoa enviando 2 ou 3 juntas (o envio substitui as anteriores).

Não copie o banco do notebook para o robô: isso apaga quem foi cadastrado pelo painel.

## 6. Trocar webcam ou caixa (só se quiser)

Sem fazer nada, continuam a webcam ligada e a caixa de sempre.

### Webcam

1. **F2+↓** e espere encerrar.
2. Troque a webcam. Deixe **só uma** conectada (a RealSense pode ficar).
3. **F2+↑** e confira o nome dela em **Robô → Webcam USB** e o ritmo do reconhecimento.
4. Recalibre a distância de parada (seção 7): outra lente muda o tamanho do rosto.

Para voltar, faça o mesmo com a antiga. Se a nova não der imagem, veja se ela oferece 640×480 em YUYV:
`v4l2-ctl -d /dev/video0 --list-formats-ext`.

**É problema de energia?** Mesma porta, 10 min para cada webcam, comparando:

```bash
journalctl -k --since "-10min" | grep -c "New USB device"
```

Se as duas caírem, a suspeita passa para o hub. Teste com um **hub USB com fonte própria**.

### Caixa de som

1. Ligue a caixa nova em **modo de pareamento**.
2. **Caixa de som → Procurar caixas** (8 s) e **Usar** ao lado dela. Deve soar um bipe. Pode ser feito com a rotina de pé.
3. Se não conectar, **a caixa anterior continua valendo**. Tente de novo.

Para voltar à antiga: **Usar** ao lado da marcada como **(padrão)**. Evite procurar durante uma aproximação: a busca usa o mesmo rádio.

Se o painel não conseguir parear, por SSH (troque o endereço):

```bash
bluetoothctl    # depois: scan on, pair XX:XX:XX:XX:XX:XX, trust XX:XX:XX:XX:XX:XX, connect XX:XX:XX:XX:XX:XX, quit
echo XX:XX:XX:XX:XX:XX > ~/ipe-2-code/data/caixa.txt     # rm desse arquivo volta à padrão
```

## 7. Ajustar a aproximação

Altere em **Operação**, salve, pare e suba de novo.

**Distância de parada:** desarmado, coloque a pessoa onde o robô deve parar e leia `caixa` em **Na
frente agora**. Use esse número em `altura_caixa_alvo_px`: **menor = para mais longe; maior = mais perto**.

| Campo | Padrão | O que faz |
|---|---|---|
| `altura_caixa_alvo_px` | 90 | Distância de parada |
| `vx` | 0,2 | Velocidade para frente (m/s) |
| `vyaw_max` / `vyaw_min` | 0,3 / 0,3 | Giro máximo e mínimo (rad/s). Abaixo de 0,3 o G1 não girou no lugar |
| `kp_giro` | 0,6 | Força da correção de giro |
| `inverter_giro` | false | `true` se virar para o lado errado |
| `centro_ok` | 0,15 | Desvio aceito ao só virar |
| `centro_para_andar` | 0,45 | Acima disso, para de andar e só gira |
| `centro_chegada` | 0,30 | Desvio aceito ao chegar perto |
| `perda_rosto_s` | 1 | Sem ver o rosto por isso, para até ver de novo |
| `desistir_s` | 10 | Sem ver o rosto por isso, desiste |
| `tempo_max_s` | 30 | Duração máxima da aproximação |
| `avisos_voz` | true | Depuração: fala "Perdi <nome> de vista" ao desistir. Use `false` para desligar |
| `estagios` | `virar,aproximar,fala,posturas` | Etapas que rodam |

## 8. Como o robô decide

**Se perder o rosto:**

| Sem ver o rosto | O que faz |
|---|---|
| Até 1 s | Continua com a última posição |
| De 1 a 10 s | Para e espera. **Se o rosto voltar, retoma sozinho** |
| 10 s | Desiste, fica em pé e fala **"Perdi <nome> de vista"** |

Ele não gira para procurar a pessoa. Depois de desistir: no manual, aperte **F2+→**; no automático, tenta assim que reconhecer a pessoa de novo.

**No automático:**

- Reconhece a pessoa em **5 quadros**; falhas de até 0,5 s não zeram a contagem.
- Só repete a mesma pessoa se **passaram 5 min e ela saiu da frente por 5 s**. **Liberar cumprimentos** ou **F2+→** ignoram essa espera.
- Pelo menos **10 s** entre dois cumprimentos quaisquer.
- Se o **tempo esgotar**, espera **60 s** antes de tentar a mesma pessoa, para não andar até ela sem parar.
- Se o gesto falhar ou for interrompido, a pessoa conta como cumprimentada: use **Liberar cumprimentos**.

## 9. Se algo der errado

| Sintoma | O que fazer |
|---|---|
| **Andou até a pessoa e não reagiu** | Veja **Últimos eventos**. `desistiu: rosto perdido`: reconhecimento falhou de perto; afaste a parada (`altura_caixa_alvo_px` menor) ou melhore a foto. `desistiu: tempo esgotado`: aumente `tempo_max_s`. `postura … falhou`: envie o log. Depois, **Liberar cumprimentos** |
| **Parou no meio** | Normalmente perdeu o rosto ou a webcam caiu. Veja a contagem de quedas no painel. Ele retoma se voltar a ver a pessoa em até 10 s |
| Chega perto demais | Diminua `altura_caixa_alvo_px`. Com muitas quedas de webcam, resolva-as primeiro: ele anda até 1 s sem imagem |
| "Não estou em equilíbrio, não vou começar." | Ponha em equilíbrio e aperte F2+↑ de novo |
| Braços errados depois de uma parada de emergência no meio de um gesto | Não ande. No suporte: F2+B e F2+A. Sem suporte: reinicie o equilíbrio pelo controle da Unitree antes de subir |
| Combo sem bipe | Caixa desligada? Veja `journalctl --user -u ipe-controle -f` |
| F2+↑ dá dois tons graves | A rotina já está de pé ou subindo: F2+↓ e espere |
| Painel não abre | Rede `IPE-G1`? Use `http://`, não `https://`. Depois, `robo_hotspot.sh estado` e `systemctl --user status ipe-painel` |
| Celular não entra no hotspot | Esqueça a rede no celular e conecte de novo |
| "A webcam reconectou" no painel | O robô reinicia a câmera sozinho. Se não voltar em ~30 s: F2+↓ e F2+↑ |
| Automático não cumprimenta | Automático ligado? O nome aparece em **Na frente agora**? A pessoa tem foto e rotina em **Pessoas**? Depois, **Liberar cumprimentos** |
| Aparece `desconhecido` | Mais luz, pessoa mais perto, foto melhor (seção 5) |
| Sem som | **Testar som**. Veja se a caixa está conectada e é a saída padrão no painel |

**Logs para enviar:**

```bash
grep -rE "desistiu|falhou|ERRO" ~/.ros/log/latest/ | tail -30
journalctl --user -u ipe-controle --since "-10min"
journalctl --user -u ipe-painel --since "-10min"
tmux attach -t rotina     # janelas "rotina" e "status"; Ctrl+b d sai sem parar
```

## 10. Conferência rápida antes de usar

Pare no primeiro item que falhar.

**Sem mexer o robô**

- [ ] Celular na `IPE-G1`, painel abre, faixa do topo sem alerta.
- [ ] **Testar som** dá bipe.
- [ ] **Subir desarmado**: em ~1 min, seu rosto aparece em **Na frente agora**.
- [ ] Foto nova cadastrada e o nome da pessoa aparece.
- [ ] **PARAR**: volta a "rotina parada".

**No suporte**

- [ ] **F2+A** levanta. Um toque rápido em **F2+B** não faz nada.

**Fora do suporte, com espaço**

- [ ] **F2+↑**, depois **F2+→** com a pessoa de lado: vira para o lado certo.
- [ ] Pessoa a ~3 m: anda, para na distância certa e faz o gesto com a fala.
- [ ] **F2+↓ andando**: para na hora.
- [ ] Pessoa sai da frente andando: para; fala "Perdi <nome> de vista" em ~10 s.
- [ ] **F2+↓ e F2+↑** em seguida: sobe de novo.
- [ ] **F2+←**: cumprimenta sozinho uma vez e não repete com a pessoa parada.

## 11. Melhorar a precisão

Em ordem de custo. **Só os itens 1 a 3 são para já:** não exigem mudar código.

| # | O que fazer | Por quê |
|---|---|---|
| 1 | **Foto feita na posição da webcam**, com boa luz | A maior variação medida foi de ângulo: 0,27 a 0,44 de cima contra 0,62 de frente |
| 2 | **2 ou 3 fotos para quem falhar** | O banco usa o centroide das fotos, então mais fotos não aumentam o falso positivo como o máximo aumentaria |
| 3 | **Webcam à altura e inclinada para o rosto; luz de frente** | Rosto de perfil, de cima ou em contraluz perde nota |
| 4 | **Calibrar o limiar** com `python -m scripts.calibrar_limiar` | 0,35 foi escolhido em campo. A referência do InsightFace é 0,30–0,45. Exige pelo menos 3 fotos por pessoa e alguém não cadastrado; com uma foto só não dá |
| 5 | **Margem entre o 1º e o 2º mais parecidos** | Proposta na revisão de 18/09 e ainda não implementada. Com limiar baixo, evita confundir duas pessoas parecidas |
| 6 | **Seguir a caixa do rosto entre quadros** | Mantém a identidade quando o nome oscila. É o que mais reduziria "perdi de vista" |
| 7 | **Distância pela profundidade da D435i** em vez de pixels | Proposta da Fase 2: parar por metros (faixa de 0,3–3 m), independentemente da câmera e do rosto |
| 8 | **Mais resolução** (ex.: 1280×720) | Rostos a 2–3 m ficam maiores, mas sobe o uso do USB. Só depois de resolver as quedas |

**Não vale trocar de modelo agora:** o `buffalo_l` já é o padrão e o reconhecedor do `antelopev2` não
mostra ganho na tabela do InsightFace (MR-ALL 91,25 contra 90,66 do R100@Glint360K).
Os pacotes `buffalo_s`/`buffalo_sc` são bem piores (71,87).

Referências: `IPE2_propostas_2026-09-18` no Dropbox (`ANALISE/00_QUADRO_VEREDITO`, `ANALISE/02`, `PROPOSTAS/FASE2`) e `UNITREE_G1_base_documentacao/MD/insightface_model_zoo_README.md`.

Testes passo a passo de cada função: [`teste-no-robo.md`](teste-no-robo.md).
