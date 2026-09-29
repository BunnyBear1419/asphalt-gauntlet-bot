from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return (ROOT / path).read_text(encoding="utf-8")

def test_recommendations_merge_into_existing_surfaces():
    server = read("ALU_Gauntlet/web/server.py")
    player = read("ALU_Gauntlet/web/static/player.html")
    player_js = read("ALU_Gauntlet/web/static/player.js")
    notifications = read("ALU_Gauntlet/cogs/notifications.py")
    records = read("ALU_Gauntlet/web/static/rsl-records.html")
    center = read("ALU_Gauntlet/web/static/rsl-command-center.html")
    center_js = read("ALU_Gauntlet/web/static/rsl-command-center.js")
    assert "/api/notifications/digest" in server
    assert "rsl-digest-frequency" in player
    assert "/api/notifications/digest" in player_js
    assert "_notify_digest" in notifications
    assert "League Activity" in records
    assert '"total_matches"' in server
    assert "cc-countdown" in center
    assert "Ends in " in center_js and "Starts in " in center_js

def test_support_remains_discord_ticket_based():
    server = read("ALU_Gauntlet/web/server.py")
    help_page = read("ALU_Gauntlet/web/static/help.html")
    center = read("ALU_Gauntlet/web/static/rsl-command-center.html")
    assert "/api/disputes" not in server
    assert "https://discord.gg/q46RQxu2fm" in help_page
    assert "Support Tickets" in center

def test_first_time_driver_experience_is_merged_into_player_center():
    player = read("ALU_Gauntlet/web/static/player.html")
    player_js = read("ALU_Gauntlet/web/static/player.js")
    assert 'id="driver-onboarding"' in player
    assert "Register for Gauntlet" in player
    assert "Read RSL Rules" in player
    assert 'rsl.driverOnboarding.dismissed' in player_js
    assert 'getElementById("dismiss-driver-onboarding")' in player_js
