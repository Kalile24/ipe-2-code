#!/usr/bin/env bash
# Comando manual de teste: libera o cumprimento já, sem esperar os 5 min nem a pessoa sair da frente.
#   ~/ipe-2-code/scripts/robo_liberar_cumprimento.sh        # todos
#   ~/ipe-2-code/scripts/robo_liberar_cumprimento.sh gil    # só o gil
# Precisa da rotina rodando (scripts/robo_rotina_cumprimento.sh).
REPO=$(cd "$(dirname "$0")/.." && pwd)
source "$REPO/scripts/ambiente_robo.sh"
ros2 param set /reaction_node liberar "${1:-todos}"
