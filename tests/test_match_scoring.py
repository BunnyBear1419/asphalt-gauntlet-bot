from ALU_Gauntlet.core.match_scoring import rsl_performance_bonus


def test_rsl_performance_bonus_keeps_3_2_as_baseline():
    assert rsl_performance_bonus(3) == 0
    assert rsl_performance_bonus(2) == 0


def test_rsl_performance_bonus_rewards_margin_without_excessive_gap():
    assert rsl_performance_bonus(4) == 8
    assert rsl_performance_bonus(1) == 8
    assert rsl_performance_bonus(5) == 15
    assert rsl_performance_bonus(0) == 15


def test_rsl_performance_bonus_is_symmetric():
    assert rsl_performance_bonus(5) == rsl_performance_bonus(0)
    assert rsl_performance_bonus(4) == rsl_performance_bonus(1)
    assert rsl_performance_bonus(3) == rsl_performance_bonus(2)


def test_rsl_performance_bonus_rejects_invalid_scores():
    for score in (-1, 6, 99):
        try:
            rsl_performance_bonus(score)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid race score was accepted")
