from glob import glob

from setuptools import find_packages, setup

package_name = "robot_reaction_ros"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/launch", glob("launch/*.launch.py")),
        (f"share/{package_name}/config", ["config/reactions.yaml", "config/operacao.yaml"]),
        (f"share/{package_name}/poses", glob("poses/*.json")),
        (f"share/{package_name}/painel", ["painel/index.html"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Marcos Kalile",
    maintainer_email="marcoskmvasconcellos@gmail.com",
    description="Reação do Unitree G1 ao reconhecer uma pessoa (rotinas militares e fala)",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "reaction_node = robot_reaction_ros.reaction_node:main",
            "body_node = robot_reaction_ros.body_node:main",
            "painel_node = robot_reaction_ros.painel_node:main",
            "camera_vigia = robot_reaction_ros.camera_vigia:main",
        ],
    },
)
