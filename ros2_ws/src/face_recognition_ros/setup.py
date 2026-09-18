from setuptools import find_packages, setup

package_name = "face_recognition_ros"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", ["launch/face_recognition.launch.py"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Marcos Kalile",
    maintainer_email="marcoskmvasconcellos@gmail.com",
    description="Nó ROS2 de reconhecimento facial para o Unitree G1",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "face_recognition_node = face_recognition_ros.face_recognition_node:main",
        ],
    },
)
