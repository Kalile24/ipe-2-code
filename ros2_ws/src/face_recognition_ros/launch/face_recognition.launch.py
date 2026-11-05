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

    video_device_arg = DeclareLaunchArgument(
        "video_device",
        default_value="/dev/video0",
        description="Dispositivo da webcam (camera:=v4l2). No robô, prefira o caminho estável "
        "/dev/v4l/by-id/...-video-index0: o número do /dev/videoN muda quando o USB reconecta",
    )

    v4l2_camera_node = Node(
        package="v4l2_camera",
        executable="v4l2_camera_node",
        name="v4l2_camera_node",
        # 15 quadros/s: o reconhecimento processa ~14-20/s, e metade do tráfego no hub USB 2.0 do
        # robô (dividido com o Wi-Fi e o Bluetooth) onde a webcam caía dezenas de vezes por hora.
        # É um pedido: a Intelbras FHD só oferece 30 ou 60 q/s em 640x480 e o driver sobe para 30.
        # Largura aqui e `largura_imagem` do operacao.yaml têm que bater (o painel avisa se não).
        parameters=[{"video_device": LaunchConfiguration("video_device"), "image_size": [640, 480],
                     "time_per_frame": [1, 15]}],
        remappings=[("/image_raw", LaunchConfiguration("image_topic"))],
        condition=IfCondition(PythonExpression(["'", LaunchConfiguration("camera"), "' == 'v4l2'"])),
        # No robô a webcam trava (para de mandar quadros) ou reconecta pelo USB; o camera_vigia do
        # robot_reaction_ros mata este nó quando o reconhecimento fica sem quadros, e ele volta aqui.
        respawn=True,
        respawn_delay=0.5,
    )

    threshold_arg = DeclareLaunchArgument(
        "similarity_threshold",
        default_value="0.45",
        description="Score mínimo para dar nome ao rosto (abaixo: desconhecido). O rotina.launch.py usa 0,35",
    )

    face_recognition_node = Node(
        package="face_recognition_ros",
        executable="face_recognition_node",
        name="face_recognition_node",
        parameters=[
            {
                "similarity_threshold": LaunchConfiguration("similarity_threshold"),
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
            threshold_arg,
            model_root_arg,
            onnx_providers_arg,
            camera_arg,
            video_device_arg,
            image_topic_arg,
            image_qos_arg,
            v4l2_camera_node,
            face_recognition_node,
        ]
    )
