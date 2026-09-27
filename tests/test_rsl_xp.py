from ALU_Gauntlet.core.rsl_xp import required_xp, level_from_xp, progress_for_xp, effective_boost

def test_xp_curves_and_progress():
    assert required_xp(1, {"curve":"linear"}) == 175
    assert required_xp(1, {"curve":"flat"}) == 1000
    assert level_from_xp(0) == 0
    assert progress_for_xp(175)["level"] == 1

def test_boosters_stack_or_choose_highest():
    settings={"role_boosters":[{"role_id":"1","percent":20},{"role_id":"2","percent":30}],"channel_boosters":[{"channel_id":"9","percent":10}],"stack_boosters":True}
    assert effective_boost(settings, ["1","2"], "9") == 1.6
    settings["stack_boosters"]=False
    assert effective_boost(settings, ["1","2"], "9") == 1.3
