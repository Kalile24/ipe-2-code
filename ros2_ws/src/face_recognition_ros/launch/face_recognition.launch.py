from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    model_name_arg = DeclareLaunchArgument(
        "model_name",
        default_value="buffalo_l",
        description="Pacote de modelo do InsightFace (ex: buffalo_l, buffalo_s, buffalo_sc)",
    )
    camera_arg = DeclareLaunchArgument(
        "camera",
        default_value="v4l2",
        description="v4l2: sobe o v4l2_camera_node (webcam local). none: não sobe câmera nenhuma — "
        "use quando outro nó (ex: realsense2_camera) já publica em image_topic",
    )
    image_topic_arg = DeclareLaunchArgument(
        "image_topic",
        default_value="/camera/color/image_raw",
        description="Tópico de imagem. realsense-ros atual publica em /camera/camera/color/image_raw",
    )
    image_qos_arg = DeclareLaunchArgument(
        "image_qos",
        default_value="sensor_data",
        description="QoS da assinatura de imagem: sensor_data (best-effort, recebe de qualquer câmera) ou default",
    )
    onnx_providers_arg = DeclareLaunchArgument(
        "onnx_providers",
        default_value="",
        description="Execution providers do ONNX Runtime, separados por vírgula, em ordem de preferência "
        "('' = default do InsightFace). No robô: TensorrtExecutionProvider,CUDAExecutionProvider,CPUExecutionProvider",
    )
    model_root_arg = DeclareLaunchArgument(
        "model_root",
        default_value="",
        description="Pasta raiz dos modelos do InsightFace ('' = ~/.insightface). Na imagem Docker: /opt/insightface",
    )

    v4l2_camera_node = Node(
        package="v4l2_camera",
        executable="v4l2_camera_node",
        name="v4l2_camera_node",
        remappings=[("/image_raw", LaunchConfiguration("image_topic"))],
        condition=IfCondition(PythonExpression(["'", LaunchConfiguration("camera"), "' == 'v4l2'"])),
    )

    face_recognition_node = Node(
        package="face_recognition_ros",
        executable="face_recognition_node",
        name="face_recognition_node",
        parameters=[
            {
                "model_name": LaunchConfiguration("model_name"),
                "image_topic": LaunchConfiguration("image_topic"),
                "image_qos": LaunchConfiguration("image_qos"),
                "model_root": LaunchConfiguration("model_root"),
                "onnx_providers": LaunchConfiguration("onnx_providers"),
            }
        ],
    )

    return LaunchDescription(
        [
            model_name_arg,
            model_root_arg,
            onnx_providers_arg,
            camera_arg,
            image_topic_arg,
            image_qos_arg,
            v4l2_camera_node,
            face_recognition_node,
        ]
    )
