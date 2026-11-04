import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression
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
    operacao_arg = DeclareLaunchArgument(
        "operacao_file",
        default_value=os.path.join(get_package_share_directory("robot_reaction_ros"), "config", "operacao.yaml"),
        description="Parâmetros de operação do body_node (estágios, aproximação); a interface escreve este arquivo",
    )
    estagios_arg = DeclareLaunchArgument(
        "estagios", default_value="", description="Sobrescreve os estágios do operacao_file ('' = os do arquivo)"
    )
    so_equilibrio_arg = DeclareLaunchArgument(
        "so_equilibrio",
        default_value="false",
        description="true: armado só começa com o robô já em equilíbrio (FSM 801), nunca damp → em pé (controle)",
    )
    # Antes do include do reconhecimento: vale para ele. 0,45 perdia o rosto de longe (a 2-3 m o
    # Gil dava 0,41 e virava desconhecido, e a aproximação desistia); desconhecidos davam < 0,15.
    threshold_arg = DeclareLaunchArgument(
        "similarity_threshold", default_value="0.35", description="Limiar do reconhecimento na rotina"
    )
    automatico_arg = DeclareLaunchArgument(
        "automatico",
        default_value="true",
        description="true: cumprimenta sozinho quem reconhece. false: só com cumprimentar_agora (controle)",
    )
    reaction_node = Node(
        package="robot_reaction_ros",
        executable="reaction_node",
        name="reaction_node",
        parameters=[
            {"reactions_file": LaunchConfiguration("reactions_file"), "automatico": LaunchConfiguration("automatico")}
        ],
    )
    # Reinicia a webcam quando o reconhecimento fica sem quadros (só com a webcam local: camera:=v4l2).
    camera_vigia = Node(
        package="robot_reaction_ros",
        executable="camera_vigia",
        name="camera_vigia",
        condition=IfCondition(PythonExpression(["'", LaunchConfiguration("camera", default="v4l2"), "' == 'v4l2'"])),
    )
    return LaunchDescription(
        [
            armed_arg, reactions_file_arg, pausa_arg, passo_arg, operacao_arg, estagios_arg, so_equilibrio_arg,
            automatico_arg, threshold_arg, recognition, reaction_node, camera_vigia, OpaqueFunction(function=_body_node),
        ]
    )


def _body_node(context: object) -> list:
    # No Foxy, um -p não sobrescreve um --params-file: as sobrescritas vão num dict DEPOIS do arquivo,
    # e `estagios` só quando foi passado (senão vale o do arquivo).
    sobrescritas = {
        "armed": LaunchConfiguration("armed"),
        "pausa_s": LaunchConfiguration("pausa_s"),
        "passo_descansar": LaunchConfiguration("passo_descansar"),
        "so_equilibrio": LaunchConfiguration("so_equilibrio"),
    }
    estagios = LaunchConfiguration("estagios").perform(context)
    if estagios:
        sobrescritas["estagios"] = estagios
    body_node = Node(
        package="robot_reaction_ros",
        executable="body_node",
        name="body_node",
        parameters=[LaunchConfiguration("operacao_file"), sobrescritas],
        # No Ctrl+C o body_node termina o passo atual, faz o a_vontade e solta os braços. Pior caso
        # (tempos em body_node.py): ESPERA_ROTINA_S 250 + SHUTDOWN_TIMEOUT_S 60 + ESPERA_PROCESSO_S
        # 10 = 320 s. O padrão do launch (SIGTERM depois de 5 s) cortaria isso no meio.
        sigterm_timeout="330",
        sigkill_timeout="10",
    )
    return [body_node]
