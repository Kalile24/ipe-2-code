import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    # Câmera + reconhecimento + reação + corpo (posturas militares e fala); o body_node é o único
    # dono dos braços. Usado por scripts/robo_rotina_cumprimento.sh.
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
    passo_arg = DeclareLaunchArgument(
        "passo_descansar",
        default_value="true",
        description="true: o descansar dá um passo curto para frente (SetVelocity 0,12 m/s) para "
        "compensar os braços indo para trás, como no ~/hhhh. false: o robô não anda.",
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
        parameters=[
            {
                "armed": LaunchConfiguration("armed"),
                "pausa_s": LaunchConfiguration("pausa_s"),
                "passo_descansar": LaunchConfiguration("passo_descansar"),
            }
        ],
        # No Ctrl+C o body_node termina o passo atual, faz o a_vontade e solta os braços. Pior caso
        # (tempos em body_node.py): ESPERA_ROTINA_S 250 + SHUTDOWN_TIMEOUT_S 60 + ESPERA_PROCESSO_S
        # 10 = 320 s. O padrão do launch (SIGTERM depois de 5 s) cortaria isso no meio.
        sigterm_timeout="330",
        sigkill_timeout="10",
    )
    return LaunchDescription([armed_arg, reactions_file_arg, pausa_arg, passo_arg, recognition, reaction_node, body_node])
