# docker/ros2.Dockerfile — ambiente de desenvolvimento x86 igual ao do robô (ROS2 Foxy,
# Ubuntu 20.04, Python 3.8), sem GPU.
FROM osrf/ros:foxy-desktop

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-pip \
        python3-dev \
        ros-foxy-cv-bridge \
        ros-foxy-vision-msgs \
        ros-foxy-v4l2-camera \
    && rm -rf /var/lib/apt/lists/*

COPY docker/requirements-ros2.txt /tmp/requirements-ros2.txt
# O pip 20.0 do Ubuntu 20.04 não reconhece wheels manylinux_2_27+.
RUN pip3 install --no-cache-dir --upgrade pip && pip3 install --no-cache-dir -r /tmp/requirements-ros2.txt

# Modelos do InsightFace pré-carregados na imagem: o download (~300 MB, GitHub) acontece ao
# instanciar FaceAnalysis, e o computador do robô pode estar sem internet. Só baixa o zip —
# não carrega ONNX — então não precisa de GPU nem de câmera no build.
ARG INSIGHTFACE_MODELS="buffalo_l"
ENV INSIGHTFACE_ROOT=/opt/insightface
RUN python3 -c "import os; from insightface.utils.storage import ensure_available; \
    [ensure_available('models', m, root=os.environ['INSIGHTFACE_ROOT']) for m in '${INSIGHTFACE_MODELS}'.split()]" \
    && rm -f ${INSIGHTFACE_ROOT}/models/*.zip \
    && ls ${INSIGHTFACE_ROOT}/models

WORKDIR /workspace

RUN echo "source /opt/ros/foxy/setup.bash" >> /root/.bashrc
