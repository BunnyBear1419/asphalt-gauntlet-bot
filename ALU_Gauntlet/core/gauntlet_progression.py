"""RSL Gauntlet progression and refresh economics.

These rules are intentionally independent of Discord/UI code so they can be
tested without MongoDB or a live bot.
"""

REFRESH_BASE_COST = 25_000
REFRESH_STEP = 50_000
REFRESH_MAX_COST = 200_000
STARTING_RSL_CREDITS = 100_000

def refresh_cost(refresh_count: int) -> int:
    count = max(0, int(refresh_count or 0))
    return min(REFRESH_MAX_COST, REFRESH_BASE_COST + (count * REFRESH_STEP))

def match_points(courses_won: int) -> int:
    """Award 3 match points for winning plus one point per race won."""
    races = int(courses_won)
    if races < 0 or races > 5:
        raise ValueError("courses_won must be between 0 and 5")
    return races + (3 if races >= 3 else 0)

def season_reward_for_rank(rank: int) -> dict:
    """Return the persistent RSL season reward package for a points rank."""
    rank = max(1, int(rank))
    if rank == 1:
        return {"tier": "Season Champion", "credits": 100_000, "badges": 10}
    if rank == 2:
        return {"tier": "Runner-Up", "credits": 90_000, "badges": 8}
    if rank == 3:
        return {"tier": "Podium", "credits": 80_000, "badges": 7}
    if rank <= 10:
        return {"tier": "Elite", "credits": 70_000, "badges": 5}
    if rank <= 25:
        return {"tier": "Contender", "credits": 50_000, "badges": 3}
    if rank <= 50:
        return {"tier": "Racer", "credits": 40_000, "badges": 2}
    if rank <= 100:
        return {"tier": "Competitor", "credits": 30_000, "badges": 1}
    return {"tier": "Finisher", "credits": 20_000, "badges": 0}
