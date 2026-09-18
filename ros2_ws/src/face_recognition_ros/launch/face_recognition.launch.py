from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
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
    )

    return LaunchDescription([v4l2_camera_node, face_recognition_node])
