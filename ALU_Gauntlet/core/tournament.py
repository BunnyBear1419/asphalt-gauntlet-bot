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
    """Build a standard double-elimination winners/losers bracket.

    The lower bracket alternates elimination rounds and merge rounds. For an
    N-player power-of-two bracket its match counts are:
    N/4, N/4, N/8, N/8, ... , 1, 1.
    """

    winners = _single_elimination(max_players)
    size = _next_power_of_two(max_players)
    winner_rounds = len(winners)
    losers_rounds = max(2, (winner_rounds - 1) * 2)

    losers = []
    for round_number in range(1, losers_rounds + 1):
        exponent = ((round_number + 1) // 2) + 1
        match_count = max(1, size // (2**exponent))
        matches = []

        for index in range(match_count):
            if round_number < losers_rounds:
                if round_number % 2:
                    target = f"LB-R{round_number + 1}-M{index}"
                else:
                    target = f"LB-R{round_number + 1}-M{index // 2}"
            else:
                target = "GF-M1"

            matches.append(
                {
                    "id": f"LB-R{round_number}-M{index}",
                    "bracket": "losers",
                    "round": round_number,
                    "player_slots": [None, None],
                    "winner_to": target,
                }
            )

        losers.append(
            {
                "round": round_number,
                "name": f"Losers Round {round_number}",
                "matches": matches,
            }
        )

    for r_idx, group in enumerate(winners):
        for match in group["matches"]:
            index = int(str(match["id"]).rsplit("-M", 1)[1])
            if r_idx == winner_rounds - 1:
                match["winner_to"] = "GF-M1"
                match["loser_to"] = f"LB-R{losers_rounds}-M0"
            else:
                # Winners bracket losses enter the next appropriate lower
                # bracket elimination round: WB R1 -> LB R1, WB R2 -> LB R3,
                # WB R3 -> LB R5, etc.
                loser_round = 2 * r_idx + 1
                match["loser_to"] = (
                    f"LB-R{loser_round}-M{index // 2}"
                )

    return {
        "type": "double_elimination",
        "winners": winners,
        "losers": losers,
        "grand_final": {
            "id": "GF-M1",
            "bracket": "grand_final",
            "round": 1,
            "player_slots": [None, None],
            "status": "waiting",
        },
        "grand_final_reset": {
            "id": "GF-M2",
            "bracket": "grand_final",
            "round": 2,
            "player_slots": [None, None],
            "status": "waiting",
            "if_necessary": True,
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
