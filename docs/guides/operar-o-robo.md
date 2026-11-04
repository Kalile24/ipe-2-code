# Operar o robô: controle, painel e hotspot

Como usar o G1 no dia a dia, sem terminal. A preparação (seção 1) é feita uma vez, por SSH; depois
tudo funciona pelo controle ou pelo celular.

**Sempre:** alguém com o controle na mão e espaço livre em volta. Ninguém aperta START nem F1+…
(são do `~/hhhh`).

> **Fora do suporte, nunca dê damp (F2+B): os motores soltam e o robô cai.**
> Para parar fora do suporte, use **F2+DOWN** ou o **PARAR** do painel.

## 1. Preparação (uma vez, por SSH)

Pelo cabo: `ssh unitree@192.168.123.164`.

**Atualizar e compilar:**

```bash
cd ~/ipe-2-code && git pull
source scripts/ambiente_robo.sh
cd ros2_ws && python3 -m colcon build --symlink-install   # tem que terminar com "3 packages finished"
```

**Conferir o arquivo de operação antigo.** O `data/operacao.yaml` fica só no robô, tem prioridade
sobre os valores novos e o `git pull` não o atualiza. Se ele existir, veja e apague; se precisar de
um ajuste antigo, refaça-o no painel depois:

```bash
cat ~/ipe-2-code/data/operacao.yaml; rm -f ~/ipe-2-code/data/operacao.yaml
```

**Ligar o controle e o painel no boot** (combine antes com quem usa o robô):

```bash
mkdir -p ~/.config/systemd/user
cp ~/ipe-2-code/scripts/systemd/ipe-controle.service ~/ipe-2-code/scripts/systemd/ipe-painel.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ipe-controle ipe-painel
systemctl --user restart ipe-controle ipe-painel    # já instalados: passam a usar o código novo
sudo loginctl enable-linger unitree                 # sobe no boot sem ninguém logado
```

**Ligar o hotspot.** Enquanto ele estiver ligado, o robô sai da rede Wi-Fi em que estava e a
transmissão da D435i do `~/cesar` para: combine antes. O cabo continua funcionando.

```bash
~/ipe-2-code/scripts/robo_hotspot.sh liga        # cria a rede IPE-G1
~/ipe-2-code/scripts/robo_hotspot.sh boot-liga   # opcional: sobe sozinho a cada boot
```

| Depois, se precisar | Comando |
|---|---|
| Ver o estado do hotspot | `robo_hotspot.sh estado` |
| Voltar para o Wi-Fi anterior | `robo_hotspot.sh desliga` |
| Não subir mais no boot | `robo_hotspot.sh boot-desliga` |

## 2. Antes de cada uso

1. **Webcam ligada no USB antes de subir a rotina.** O script escolhe a câmera ao subir.
2. **Caixa de som Bluetooth ligada.** Sem ela não há fala nem bipes, mas o robô funciona.
3. **Robô em equilíbrio** (FSM 801), de um destes jeitos:
   - pelo controle da Unitree; ou
   - no suporte, com o robô em damp: segure **F2+A** por 1,5 s. Ele levanta e fica em equilíbrio.

## 3. Conectar o celular ao painel

1. Conecte-se à rede Wi-Fi **`IPE-G1`**, senha **`ipe-g1-2026`**.
2. Abra **`http://10.42.0.1:8080`**.

O celular pode avisar que a rede não tem internet: continue conectado. O painel não tem login; a
proteção é a senha do hotspot.

## 4. Controle

O botão **F2** vem escrito **F3** em alguns controles G1. Segure F2 e aperte o outro botão.

| Combo | O que faz | Bipe |
|---|---|---|
| **F2 + ↑** | Sobe a rotina armada. Só com o robô em equilíbrio. Reações automáticas desligadas | dois tons subindo |
| **F2 + →** | Cumprimenta agora quem está sendo reconhecido | um tom |
| **F2 + ←** | Liga/desliga as reações automáticas (o robô fala o estado) | dois tons iguais |
| **F2 + ↓** | **Para:** velocidade zero na hora, braços de volta, encerra a rotina. Também aborta um F2+A em andamento | um tom grave; depois dois descendo ao encerrar |
| **F2 + A** (segurar 1,5 s) | Levanta no suporte. Só com o robô mole | três bipes curtos ao começar a segurar |
| **F2 + B** (segurar 1,5 s) | **Damp. Só no suporte.** Recusado com a rotina de pé (F2+↓ antes) | três bipes curtos; depois três tons descendo |

**Dois tons graves = recusado:** o combo não fez nada. Soltar F2+A ou F2+B antes de 1,5 s cancela.

O L2+B da Unitree não faz damp no modo de equilíbrio.

### Uso normal

1. Com o robô em equilíbrio, **F2+↑**. Espere a rotina subir (cerca de 1 min até o reconhecimento
   funcionar; acompanhe no painel).
2. Escolha o modo:
   - **Manual:** com a pessoa na frente, **F2+→**.
   - **Automático:** **F2+←** uma vez. O robô cumprimenta sozinho quem reconhece.
3. O robô vira, anda até a pessoa, para, faz a rotina (sentido, continência, fala, desc. arma, à
   vontade) e volta à posição em que anda.
4. Ao terminar, **F2+↓**. Espere os dois tons descendo antes de subir de novo.

## 5. Painel

| Cartão | Para que serve |
|---|---|
| **Robô** | Estágio atual, rotina, armado/desarmado, reações, webcam (com contagem de quedas), caixa de som e reconhecimento |
| **Na frente agora** | Quem está sendo visto, a nota e a altura da caixa do rosto em pixels |
| **Últimos eventos** | O que o robô fez, com a hora |
| **Comandos** | Os botões abaixo |
| **Operação** | Os ajustes da seção 6. Valem na próxima subida |
| **Cadastrar pessoa** | Cadastro por foto (seção 8) |

| Botão | O que faz |
|---|---|
| **Subir desarmado** | Reconhecimento e fala, **sem mexer o robô**, com o automático ligado. Bom para testar |
| **Subir armado** | Igual ao F2+↑: o robô se mexe, com o automático desligado |
| **Cumprimentar agora** | Igual ao F2+→ |
| **Liga/desliga automático** | Igual ao F2+← |
| **Liberar cumprimentos** | Todos podem ser cumprimentados de novo já, sem esperar |
| **PARAR** | Igual ao F2+↓ |

## 6. Ajustar a aproximação

Altere no cartão **Operação**, salve, pare a rotina e suba de novo.

**Parou perto ou longe demais?** Com o robô desarmado, coloque a pessoa onde o robô deve parar e leia
`caixa` em **Na frente agora**. Use esse número em `altura_caixa_alvo_px`: **menor para mais longe,
maior para mais perto.** Recalibre sempre que trocar a webcam ou a posição dela.

| Campo | Padrão | O que faz |
|---|---|---|
| `estagios` | `virar,aproximar,fala,posturas` | Etapas que rodam |
| `altura_caixa_alvo_px` | 90 | Distância de parada |
| `vx` | 0,2 | Velocidade para frente (m/s) |
| `vyaw_max` / `vyaw_min` | 0,3 / 0,3 | Giro máximo e mínimo (rad/s). Abaixo de 0,3 o G1 não girou no lugar nos testes |
| `kp_giro` | 0,6 | Força da correção de giro |
| `inverter_giro` | false | Use `true` se ele virar para o lado errado |
| `centro_ok` | 0,15 | Desvio aceito para considerar de frente ao só virar |
| `centro_para_andar` | 0,45 | Acima desse desvio, para de andar e só gira |
| `centro_chegada` | 0,30 | Desvio aceito ao chegar perto |
| `perda_rosto_s` | 0,5 | Sem ver o rosto por esse tempo, para até ver de novo |
| `desistir_s` | 10 | Sem ver o rosto por esse tempo, desiste |
| `tempo_max_s` | 30 | Duração máxima da aproximação |

O robô para quando não vê o rosto, de propósito: andar sem imagem o levava perto demais. Por isso,
cada queda da webcam causa uma parada. Aumentar `perda_rosto_s` reduz as paradas curtas, mas o robô
anda mais tempo sem enxergar.

## 7. Como o automático decide

- Precisa reconhecer a pessoa em **5 quadros**. Falhas de até 0,5 s não zeram a contagem.
- Depois de cumprimentar, só repete a mesma pessoa se **passaram 5 min e ela saiu da frente por 5 s**.
- Entre dois cumprimentos quaisquer há pelo menos **10 s**.
- Se a aproximação **desistir**, a pessoa não conta como cumprimentada, e o robô tenta de novo só depois de **60 s**.
- Se a rotina for interrompida com F2+↓ ou **PARAR**, a pessoa conta como cumprimentada. **Liberar cumprimentos** desfaz isso.

## 8. Cadastrar pessoas

1. Suba a rotina (desarmada basta).
2. Em **Cadastrar pessoa**, digite o nome em minúsculas, sem espaço, e envie de 1 a 5 fotos de frente, com uma pessoa por foto.
3. A pessoa passa a ser reconhecida na hora.

Para ser **cumprimentada**, ela também precisa de uma rotina no `config/reactions.yaml`. Hoje há
rotina para **gil, marcos e bianco**, e os três precisam estar cadastrados no robô.

Não copie o banco do notebook para o robô: isso apaga quem foi cadastrado pelo painel.

## 9. Trocar a webcam

Não é preciso mudar configuração, e qualquer webcam USB comum deve servir:

1. **F2+↓** e espere encerrar.
2. Tire a webcam antiga e ligue a nova. Deixe **só uma webcam** conectada (a RealSense pode ficar).
3. **F2+↑** e confira a imagem e o ritmo do reconhecimento no painel.
4. Recalibre `altura_caixa_alvo_px` (seção 6).

Para saber se a causa das quedas é energia, use a mesma porta e compare por 10 min cada webcam:

```bash
journalctl -k --since "-10min" | grep -c "New USB device"
```

Se as duas caírem, teste com um hub USB com fonte própria.

## 10. Se algo der errado

| Sintoma | O que fazer |
|---|---|
| "Não estou em equilíbrio, não vou começar." | Ponha o robô em equilíbrio e aperte F2+↑ de novo. Logo depois de outra rodada, os braços podem levar um tempo para soltar: espere alguns segundos e repita |
| Combo sem efeito e sem bipe | Veja se a caixa está ligada e confira `journalctl --user -u ipe-controle -f` |
| F2+↑ dá dois tons graves | A rotina já está de pé ou subindo. Use F2+↓ e espere encerrar |
| Painel não abre | Confirme que está na rede `IPE-G1` e use `http://`, não `https://`. Depois confira `robo_hotspot.sh estado` e `systemctl --user status ipe-painel` |
| Celular não entra no hotspot | Esqueça a rede no celular e conecte de novo |
| Painel mostra "A webcam reconectou" | O robô reinicia a câmera sozinho. Se a imagem não voltar em ~30 s, F2+↓ e F2+↑ |
| Webcam com muitas quedas | Seção 9. O robô se recupera, mas para a cada queda |
| Robô não cumprimenta no automático | Confirme "Reações automáticas: ligadas" e o nome em **Na frente agora**. Já cumprimentada: use **Liberar cumprimentos** |
| Reconhece como `desconhecido` | Melhore a luz, aproxime a pessoa ou recadastre com mais fotos |
| Vira para o lado errado | `inverter_giro: true` |
| Desiste no meio (`desistiu:` em **Últimos eventos**) | Rosto perdido: veja a webcam. Tempo esgotado: confira se há caminho livre e aumente `tempo_max_s` |

**Logs para enviar:**

```bash
journalctl --user -u ipe-controle --since "-10min"
journalctl --user -u ipe-painel --since "-10min"
tmux attach -t rotina    # janelas "rotina" e "status"; Ctrl+b d sai sem parar
```

## 11. Conferência antes de usar de verdade

Faça uma vez depois de atualizar, na ordem. Para no primeiro item que falhar.

**Sem mexer o robô:**

- [ ] O celular entra na `IPE-G1` e o painel abre.
- [ ] **Subir desarmado:** em ~1 min, câmera e reconhecimento ficam verdes e seu rosto aparece.
- [ ] A pessoa cadastrada aparece com o nome, e a fala sai pela caixa.
- [ ] **PARAR:** a rotina encerra e o estágio volta para "rotina parada".

**No suporte:**

- [ ] Com o robô em damp, **F2+A** levanta até o equilíbrio.
- [ ] De novo em damp: **F2+A** e, durante a subida, **F2+↓** aborta. Depois, **F2+B** dá damp.
- [ ] Toque rápido em **F2+B** não faz nada.

**Fora do suporte, com espaço:**

- [ ] **F2+↑** sobe; **F2+→** com a pessoa de lado: o robô vira para o lado certo.
- [ ] Com a pessoa a ~3 m, ele anda e para na distância certa. Se não, seção 6.
- [ ] **F2+↓ durante a caminhada** para na hora.
- [ ] Tapar a webcam durante a caminhada: ele para em ~0,5 s e, destapada, continua.
- [ ] **F2+↓ e F2+↑ logo em seguida:** sobe de novo sem "Não estou em equilíbrio". Anote quanto tempo precisou esperar.
- [ ] **F2+←**, automático ligado: cumprimenta sozinho uma vez e não repete com a pessoa parada na frente.

Passo a passo mais detalhado para testes: [`teste-no-robo.md`](teste-no-robo.md).
