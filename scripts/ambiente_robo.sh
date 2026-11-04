# Ambiente ROS2 Foxy + CycloneDDS + venv do projeto no robô (o mesmo do robo_tmux.sh).
# Uso: source ~/ipe-2-code/scripts/ambiente_robo.sh
REPO=${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
source /opt/ros/foxy/setup.bash
source ~/cyclonedds_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp CYCLONEDDS_URI=$HOME/cyclonedds_ws/cyclonedds.xml
export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH
source "$REPO/.venv/bin/activate"
source "$REPO/ros2_ws/install/setup.bash"
