"""Tournament bracket generation utilities.

The generator creates deterministic match structures from the tournament's
selected format and player limit. Player registration and result verification
remain separate concerns.
"""

from __future__ import annotations

from typing import Any


SUPPORTED_TOURNAMENT_FORMATS = (
    "single_elimination",
    "double_elimination",
    "round_robin",
)


def _next_power_of_two(value: int) -> int:
    size = 1
    while size < value:
        size *= 2
    return size


def _single_elimination(max_players: int) -> list[dict[str, Any]]:
    size = _next_power_of_two(max_players)
    rounds = []
    match_count = size // 2
    round_number = 1

    while match_count >= 1:
        rounds.append(
            {
                "round": round_number,
                "name": "Final" if match_count == 1 else f"Round {round_number}",
                "matches": [
                    {
                        "id": f"WB-R{round_number}-M{index}",
                        "bracket": "winners",
                        "round": round_number,
                        "player_slots": [None, None],
                        "winner_to": (
                            f"WB-R{round_number + 1}-M{index // 2}"
                            if match_count > 1
                            else None
                        ),
                    }
                    for index in range(match_count)
                ],
            }
        )
        match_count //= 2
        round_number += 1

    return rounds


def _double_elimination(max_players: int) -> dict[str, Any]:
    winners = _single_elimination(max_players)
    size = _next_power_of_two(max_players)
    winner_rounds = len(winners)
    # Standard double-elimination cadence: after each winners round,
    # eliminated winners feed into the appropriate losers round.
    losers_rounds = max(1, (winner_rounds - 1) * 2)
    losers = []
    for round_number in range(1, losers_rounds + 1):
        match_count = max(1, size // (2 ** ((round_number + 1) // 2)))
        losers.append({
            "round": round_number,
            "name": f"Losers Round {round_number}",
            "matches": [{
                "id": f"LB-R{round_number}-M{index}",
                "bracket": "losers",
                "round": round_number,
                "player_slots": [None, None],
                "winner_to": (
                    f"LB-R{round_number + 1}-M{index // 2}"
                    if round_number < losers_rounds else "GF-M1"
                ),
            } for index in range(match_count)],
        })

    # Wire winners-bracket advancement and each winners loss into the
    # appropriate losers-bracket round.  The loser feed is explicit so
    # result verification can advance either side without guessing.
    for r_idx, group in enumerate(winners):
        if r_idx == len(winners) - 1:
            continue
        for match in group["matches"]:
            match["loser_to"] = f"LB-R{max(1, r_idx * 2 + 1)}-M{match['id'].split('-M')[-1] if r_idx == 0 else int(match['id'].split('-M')[-1]) // 2}"

    return {
        "type": "double_elimination",
        "winners": winners,
        "losers": losers,
        "grand_final": {
            "id": "GF-M1",
            "bracket": "grand_final",
            "round": 1,
            "player_slots": [None, None],
        },
    }

def _round_robin(max_players: int) -> list[dict[str, Any]]:
    # Berger-style round robin schedule. For odd player counts, add a bye.
    slots = list(range(1, max_players + 1))
    if len(slots) % 2:
        slots.append(None)

    rounds = []
    total_rounds = len(slots) - 1
    for round_number in range(1, total_rounds + 1):
        matches = []
        half = len(slots) // 2
        for index in range(half):
            a = slots[index]
            b = slots[-1 - index]
            if a is not None and b is not None:
                matches.append(
                    {
                        "id": f"RR-R{round_number}-M{len(matches) + 1}",
                        "bracket": "round_robin",
                        "round": round_number,
                        "player_slots": [None, None],
                        "seed_slots": [a, b],
                    }
                )
        rounds.append({"round": round_number, "name": f"Round {round_number}", "matches": matches})
        slots = [slots[0], slots[-1], *slots[1:-1]]

    return rounds


def generate_tournament_bracket(format: str, max_players: int) -> dict[str, Any]:
    """Return an empty bracket structure for a new tournament."""
    fmt = str(format or "").strip().casefold()
    count = int(max_players)

    if fmt not in SUPPORTED_TOURNAMENT_FORMATS:
        raise ValueError("Unsupported tournament format.")
    if count < 2 or count > 256:
        raise ValueError("Maximum players must be between 2 and 256.")

    if fmt == "single_elimination":
        return {"type": fmt, "player_limit": count, "rounds": _single_elimination(count)}
    if fmt == "double_elimination":
        return {"type": fmt, "player_limit": count, **_double_elimination(count)}
    return {"type": fmt, "player_limit": count, "rounds": _round_robin(count)}
