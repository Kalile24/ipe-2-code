import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    # Câmera + reconhecimento: o launch de face_recognition_ros, sem mudanças. Os argumentos dele
    # (camera, video_device, onnx_providers, model_root...) chegam pela linha de comando.
    recognition = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(get_package_share_directory("face_recognition_ros"), "launch", "face_recognition.launch.py")
        )
    )
    armed_arg = DeclareLaunchArgument(
        "armed",
        default_value="false",
        description="true: o gesture_node mexe o braço de verdade. false: dry-run (só loga). "
        "Também dá para armar depois: ros2 service call /gesture_node/set_armed std_srvs/srv/SetBool '{data: true}'",
    )
    reactions_file_arg = DeclareLaunchArgument(
        "reactions_file",
        default_value="",
        description="Mapa pessoa -> gesto ('' = config/reactions.yaml do pacote)",
    )
    reaction_node = Node(
        package="robot_reaction_ros",
        executable="reaction_node",
        name="reaction_node",
        parameters=[{"reactions_file": LaunchConfiguration("reactions_file")}],
    )
    gesture_node = Node(
        package="robot_reaction_ros",
        executable="gesture_node",
        name="gesture_node",
        parameters=[{"armed": LaunchConfiguration("armed")}],
    )
    return LaunchDescription([armed_arg, reactions_file_arg, recognition, reaction_node, gesture_node])
