from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    model_name_arg = DeclareLaunchArgument(
        "model_name",
        default_value="buffalo_l",
        description="Pacote de modelo do InsightFace (ex: buffalo_l, buffalo_s, buffalo_sc)",
    )

    v4l2_camera_node = Node(
        package="v4l2_camera",
        executable="v4l2_camera_node",
        name="v4l2_camera_node",
        remappings=[("/image_raw", "/camera/color/image_raw")],
    )

    face_recognition_node = Node(
        package="face_recognition_ros",
        executable="face_recognition_node",
        name="face_recognition_node",
        parameters=[{"model_name": LaunchConfiguration("model_name")}],
    )

    return LaunchDescription([model_name_arg, v4l2_camera_node, face_recognition_node])
