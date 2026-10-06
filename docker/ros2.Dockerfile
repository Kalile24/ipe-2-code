# docker/ros2.Dockerfile
FROM osrf/ros:humble-desktop

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-pip \
        ros-humble-cv-bridge \
        ros-humble-vision-msgs \
        ros-humble-v4l2-camera \
    && rm -rf /var/lib/apt/lists/*

COPY docker/requirements-ros2.txt /tmp/requirements-ros2.txt
RUN pip install --no-cache-dir -r /tmp/requirements-ros2.txt

# Modelos do InsightFace pré-carregados na imagem: o download (~300 MB, GitHub) acontece ao
# instanciar FaceAnalysis, e o computador do robô não tem internet. Só baixa o zip — não
# carrega ONNX — então não precisa de GPU nem de câmera no build.
ARG INSIGHTFACE_MODELS="buffalo_l"
ENV INSIGHTFACE_ROOT=/opt/insightface
RUN python3 -c "import os; from insightface.utils.storage import ensure_available; \
    [ensure_available('models', m, root=os.environ['INSIGHTFACE_ROOT']) for m in '${INSIGHTFACE_MODELS}'.split()]" \
    && rm -f ${INSIGHTFACE_ROOT}/models/*.zip \
    && ls ${INSIGHTFACE_ROOT}/models

WORKDIR /workspace

RUN echo "source /opt/ros/humble/setup.bash" >> /root/.bashrc
