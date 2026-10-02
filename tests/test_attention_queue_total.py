import asyncio

from ALU_Gauntlet.core.rsl_reliability import attention_queue_snapshot


class _Collection:
    def __init__(self, count):
        self.count = count

    async def count_documents(self, _query):
        return self.count

    async def find_one(self, *_args, **_kwargs):
        return {"gauntlet_role_snapshot": {"Role": ["1"]}}


class _DB:
    """Every queue holds exactly 2 items, the coin ledger holds 3."""

    rsl_economy_transactions = _Collection(3)
    season_state = _Collection(0)

    def __getitem__(self, _name):
        return _Collection(2)


def test_attention_total_is_the_sum_of_each_queue_exactly_once():
    counts = asyncio.run(attention_queue_snapshot(_DB(), "guild-1"))

    queue_keys = [k for k in counts if k != "total"]
    assert "bonus_staff_review" in counts
    assert counts["total"] == sum(counts[k] for k in queue_keys)
    # 8 queues x 2 + 3 pending coin rows + 1 season role snapshot
    assert counts["total"] == 8 * 2 + 3 + 1
