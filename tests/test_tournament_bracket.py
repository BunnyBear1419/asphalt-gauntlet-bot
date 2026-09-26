"""Regression tests for the RSL tournament bracket engine."""

from ALU_Gauntlet.core.tournament import generate_tournament_bracket


def _matches(bracket):
    rows = []
    for key in ("rounds", "winners", "losers"):
        for group in bracket.get(key, []):
            rows.extend(group.get("matches", []))
    for key in ("grand_final", "grand_final_reset"):
        match = bracket.get(key)
        if isinstance(match, dict):
            rows.append(match)
    return rows


def test_single_elimination_supports_non_power_of_two_limits():
    bracket = generate_tournament_bracket("single_elimination", 32)
    assert bracket["type"] == "single_elimination"
    assert bracket["player_limit"] == 32
    assert len(bracket["rounds"]) == 6
    assert len(bracket["rounds"][0]["matches"]) == 16
    assert len(bracket["rounds"][-1]["matches"]) == 1


def test_single_elimination_match_links_are_valid():
    bracket = generate_tournament_bracket("single_elimination", 16)
    matches = {m["id"]: m for m in _matches(bracket)}
    assert len(matches) == 15
    for match in matches.values():
        target = match.get("winner_to")
        if target:
            assert target in matches


def test_double_elimination_has_winners_losers_and_grand_final():
    bracket = generate_tournament_bracket("double_elimination", 16)
    matches = {m["id"]: m for m in _matches(bracket)}
    assert bracket["type"] == "double_elimination"
    assert bracket["winners"]
    assert bracket["losers"]
    assert bracket["grand_final"]["id"] == "GF-M1"
    assert bracket["grand_final_reset"]["if_necessary"] is True

    for match in matches.values():
        for field in ("winner_to", "loser_to"):
            target = match.get(field)
            if target:
                assert target in matches


def test_round_robin_schedule_gives_each_pair_once():
    bracket = generate_tournament_bracket("round_robin", 6)
    pairs = []
    for group in bracket["rounds"]:
        for match in group["matches"]:
            a, b = match["seed_slots"]
            pairs.append(tuple(sorted((a, b))))

    assert len(pairs) == 15
    assert len(set(pairs)) == 15
    assert len(bracket["rounds"]) == 5


def test_bracket_limits_and_formats_are_rejected():
    for fmt in ("single_elimination", "double_elimination", "round_robin"):
        for count in (2, 256):
            assert generate_tournament_bracket(fmt, count)["type"] == fmt

    for fmt, count in (("unknown", 8), ("single_elimination", 1), ("round_robin", 257)):
        try:
            generate_tournament_bracket(fmt, count)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid tournament bracket input was accepted.")
