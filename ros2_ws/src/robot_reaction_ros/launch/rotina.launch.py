import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    # Câmera + reconhecimento + reação + corpo (posturas militares e fala). Sem o gesture_node:
    # o body_node é o único dono dos braços. Usado por scripts/robo_rotina_cumprimento.sh.
    recognition = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(get_package_share_directory("face_recognition_ros"), "launch", "face_recognition.launch.py")
        )
    )
    armed_arg = DeclareLaunchArgument(
        "armed",
        default_value="false",
        description="true: na partida o body_node levanta o robô (como o F1+UP) e executa as posturas. "
        "false: só fala; posturas no log. Só vale na partida.",
    )
    reactions_file_arg = DeclareLaunchArgument(
        "reactions_file",
        default_value="",
        description="Mapa pessoa -> reação ('' = config/reactions.yaml do pacote)",
    )
    pausa_arg = DeclareLaunchArgument(
        "pausa_s", default_value="0.5", description="Pausa depois de cada postura da rotina (s)"
    )
    reaction_node = Node(
        package="robot_reaction_ros",
        executable="reaction_node",
        name="reaction_node",
        parameters=[{"reactions_file": LaunchConfiguration("reactions_file")}],
    )
    body_node = Node(
        package="robot_reaction_ros",
        executable="body_node",
        name="body_node",
        parameters=[{"armed": LaunchConfiguration("armed"), "pausa_s": LaunchConfiguration("pausa_s")}],
        # No Ctrl+C o body_node espera o passo atual e devolve os braços (até ~2 min no pior caso);
        # o padrão do launch (SIGTERM depois de 5 s) cortaria isso no meio.
        sigterm_timeout="120",
        sigkill_timeout="10",
    )
    return LaunchDescription([armed_arg, reactions_file_arg, pausa_arg, recognition, reaction_node, body_node])
