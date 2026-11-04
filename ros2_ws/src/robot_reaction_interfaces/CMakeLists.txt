cmake_minimum_required(VERSION 3.5)
project(robot_reaction_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME} "action/Rotina.action")

ament_export_dependencies(rosidl_default_runtime)
ament_package()
