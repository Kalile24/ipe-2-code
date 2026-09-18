# Nó ROS2 via Docker — guia detalhado

Este guia cobre o passo a passo completo para buildar, rodar e depurar o nó
`face_recognition_node` num ambiente ROS2 Humble local, sem precisar de
acesso ao robô Unitree G1. Para o resumo rápido ("só quero rodar"), veja o
[README](../../README.md#nó-ros2-docker).

Todos os problemas de ambiente descritos na seção **Problemas comuns** já
estão corrigidos em `docker/ros2.Dockerfile`/`docker/requirements-ros2.txt` —
essa seção existe para explicar *por quê* aquelas versões estão fixadas
daquele jeito, caso você precise mexer nelas no futuro.

## Pré-requisitos

- Docker instalado e seu usuário no grupo `docker`:
  ```bash
  groups                        # "docker" precisa aparecer na lista
  sudo usermod -aG docker $USER # se não aparecer
  newgrp docker                 # ou feche/abra o terminal, pra aplicar
  ```
- Uma webcam reconhecida pelo Linux em `/dev/video0` (`ls /dev/video*` pra conferir).

## 1. Build da imagem

```bash
docker build -f docker/ros2.Dockerfile -t face-recognition-ros2:local .
```

Isso só precisa ser refeito quando `docker/ros2.Dockerfile` ou
`docker/requirements-ros2.txt` mudarem — é a "receita"; o resto dos arquivos
do repositório entra ao vivo via bind mount (`-v`) nos comandos abaixo, sem
precisar de rebuild.

## 2. Smoke test — confirma que as libs coexistem sem conflito

```bash
docker run --rm -v "$(pwd)":/workspace -w /workspace face-recognition-ros2:local \
  bash -lc "source /opt/ros/humble/setup.bash && pip install -e . && python3 -c 'import cv2, rclpy, cv_bridge, vision_msgs; print(\"OK\", cv2.__version__)'"
```

Espera-se `OK <versão>`. Isso confirma que `numpy`/`opencv-python`/`onnxruntime`
(pip) não quebraram o `cv_bridge` (compilado contra o `numpy` do sistema).

## 3. Build e teste do pacote ROS2

```bash
docker run --rm -it --device=/dev/video0 --group-add video \
  -v "$(pwd)":/workspace -w /workspace face-recognition-ros2:local bash
```

Dentro do container:

```bash
pip install -e .
cd ros2_ws
colcon build --symlink-install
colcon test
colcon test-result --verbose
```

Espera-se `Summary: 1 package finished` nos dois, e os 3 testes de
`test_message_builder.py` passando no `colcon test-result`.

**Rode sempre a partir de `ros2_ws/`** — o `colcon` procura pacotes
recursivamente a partir do diretório atual, então rodar na raiz do repo
também "funciona", mas cria um `build/`/`install/`/`log/` duplicado e
solto na raiz em vez de dentro de `ros2_ws/`, o que confunde o próximo
passo (qual `install/setup.bash` sourcear).

## 4. Rodar com a webcam (dois terminais)

**Terminal A** (o mesmo container do passo 3, ou um novo com as mesmas flags
`--device`/`--group-add`):

```bash
source install/setup.bash    # a partir de dentro de ros2_ws/
ros2 launch face_recognition_ros face_recognition.launch.py
```

**Terminal B** — entre no *mesmo* container (não crie um novo):

```bash
docker ps                              # anota o CONTAINER ID/NAME
docker exec -it <container> bash
source /opt/ros/humble/setup.bash
cd /workspace/ros2_ws && source install/setup.bash
ros2 topic echo /face_recognition/detections
```

Com alguém na frente da câmera, aparece `class_id: desconhecido` (ninguém
cadastrado) ou o nome da pessoa, se cadastrada (próxima seção). Sem ninguém
na frente, o array `detections` vem vazio — não é erro, é o sinal de que o
nó está "vivo".

## 5. Cadastrar uma pessoa

Fora do container (o `.venv` do host já tem tudo que esse script precisa —
não depende de ROS2):

```bash
mkdir -p data/known_faces/nome_da_pessoa
# copie 1+ fotos do rosto dela pra essa pasta
.venv/bin/python -m apps.enroll
```

O nó só lê o banco de identidades **uma vez**, na inicialização — depois de
cadastrar alguém novo, reinicie o `ros2 launch` (Terminal A: `Ctrl+C` e rode
de novo) pra ele carregar o cadastro atualizado.

## 6. Escolha de modelo (latência vs. acurácia)

O InsightFace empacota três combinações de detector+reconhecedor, do mais
preciso/pesado ao mais leve/rápido: `buffalo_l` (default), `buffalo_s`,
`buffalo_sc`. Testado em CPU (sem GPU): `buffalo_l` roda visivelmente
travado (~900ms por reconhecimento); `buffalo_sc` roda fluido, ao custo de
acurácia — para poucas pessoas cadastradas essa perda tende a ser pequena.

Cada modelo tem seu **próprio banco de identidades**
(`data/identity_db_<modelo>.npz`/`.json`) — embeddings de modelos
diferentes não são comparáveis entre si, então trocar de modelo sem
recadastrar simplesmente não encontra ninguém (não dá resultado errado
silenciosamente).

```bash
# protótipo standalone
.venv/bin/python -m apps.enroll --model buffalo_sc
.venv/bin/python -m apps.webcam_demo --model buffalo_sc

# nó ROS2 (parâmetro de launch)
ros2 launch face_recognition_ros face_recognition.launch.py model_name:=buffalo_sc
```

`--model`/`model_name` default para `buffalo_l` (`core.config.MODEL_NAME`) se omitido.

## Problemas comuns (já corrigidos no repo, contexto pra quem for mexer)

- **`ModuleNotFoundError: No module named 'core'` mesmo com `pip install -e .`
  "funcionando"** — se o `pip install -e .` reclamar de "missing the
  build_editable hook... PEP 660", é porque o `setuptools` do container (fixado
  em `docker/requirements-ros2.txt`) é antigo demais pra instalação editável
  moderna. Por isso existe um `setup.py` mínimo na raiz do repo: ele dá ao
  `pip` um caminho alternativo de instalação editável (`setup.py develop`)
  que funciona mesmo com `setuptools` antigo.
- **`PackageNotFoundError` ao rodar `ros2 launch`, mesmo com `colcon build`
  "funcionando"** — `setuptools` novo demais quebra como o `colcon build
  --symlink-install` registra os metadados do pacote ROS2. Por isso
  `docker/requirements-ros2.txt` fixa `setuptools==58.2.0`.
- **`colcon test` falha com `PluginValidationError` em `launch_testing`** — um
  plugin de teste do próprio ROS2 (`launch_testing`) não é compatível com
  `pytest>=8.1`. Por isso `docker/requirements-ros2.txt` fixa
  `pytest==7.4.4`.
- **Imagem/pacote pip não instala no container** — `numpy`/`onnxruntime` mais
  recentes (as versões do `requirements.txt` da raiz, usadas pelo protótipo
  standalone) não têm build pra Python 3.10 (o Python do Ubuntu 22.04/ROS2
  Humble). Por isso existe `docker/requirements-ros2.txt` com versões
  específicas pro container, separadas do `requirements.txt` do host.
- **`docker run ... face-recognition-ros2` reclama de "pull access denied"**
  — faltou a tag: use `face-recognition-ros2:local`, exatamente como no
  `docker build`.
- **`bash` "roda e volta na hora" sem erro** — faltaram as flags `-it`
  (interativo + terminal), sem elas o container liga, não recebe teclado, e
  desliga imediatamente.
- **`permission denied ... docker.sock`** — seu usuário não está no grupo
  `docker`, ou você entrou nele mas o terminal atual é de antes dessa
  mudança (rode `newgrp docker` ou abra um terminal novo).

## Ver também

- [Spec de design do nó ROS2](../superpowers/specs/2026-09-12-ros2-node-migration-design.md)
- [Plano de implementação](../superpowers/plans/2026-09-17-ros2-node-migration.md)
