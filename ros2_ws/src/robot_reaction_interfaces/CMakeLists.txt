cmake_minimum_required(VERSION 3.5)
project(robot_reaction_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(sensor_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME} "action/Rotina.action" "srv/Cadastrar.srv" DEPENDENCIES sensor_msgs)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
