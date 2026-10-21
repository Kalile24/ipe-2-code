from __future__ import annotations

import pytest

from core.reaction_policy import GESTOS, RELEASE_ARM, ReactionConfigError, load_reactions


def test_gesture_ids_match_the_sdk_action_map():
    assert GESTOS["high wave"] == 26
    assert GESTOS["shake hand"] == 27
    assert GESTOS[RELEASE_ARM] == 99


def test_valid_map_returns_name_to_gesture():
    raw = {"gil": {"gesto": "high wave"}, "marcos": {"gesto": "shake hand"}}
    assert load_reactions(raw) == {"gil": "high wave", "marcos": "shake hand"}


@pytest.mark.parametrize(
    "raw, trecho",
    [
        (None, "mapa"),  # arquivo YAML vazio
        (["gil"], "mapa"),
        ({}, "nenhuma pessoa"),
        ({"gil": "high wave"}, "gil"),
        ({"gil": {}}, "gesto"),
        ({"gil": {"gesture": "high wave"}}, "gesture"),
        ({"gil": {"gesto": "high wave", "fala": "oi"}}, "fala"),
        ({"gil": {"gesto": "continencia"}}, "continencia"),
        ({1: {"gesto": "high wave"}}, "1"),
    ],
)
def test_invalid_maps_fail_naming_the_problem(raw, trecho):
    with pytest.raises(ReactionConfigError, match=trecho):
        load_reactions(raw)
