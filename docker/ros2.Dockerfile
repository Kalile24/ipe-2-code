# docker/ros2.Dockerfile
FROM osrf/ros:humble-desktop

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-pip \
        ros-humble-cv-bridge \
        ros-humble-vision-msgs \
        ros-humble-v4l2-camera \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /workspace

RUN echo "source /opt/ros/humble/setup.bash" >> /root/.bashrc
