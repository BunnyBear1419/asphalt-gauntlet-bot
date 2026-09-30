from pathlib import Path
import importlib

def test_rsl_ticket_cog_exists_and_loads():
    module = importlib.import_module("ALU_Gauntlet.cogs.tickets")
    assert hasattr(module, "TicketCog")
    assert hasattr(module, "TicketPanelView")
    assert len(module.DEFAULT_TYPES) == 6

def test_ticket_center_has_restart_persistent_views():
    source = Path("ALU_Gauntlet/cogs/tickets.py").read_text(encoding="utf-8")
    assert "timeout=None" in source
    assert "restore_views" in source
    assert "self.bot.add_view" in source

def test_ticket_center_uses_canonical_guild_scoping():
    source = Path("ALU_Gauntlet/cogs/tickets.py").read_text(encoding="utf-8")
    assert '"guild_id":str(guild.id)' in source
    assert '"guild_id":str(guild_id)' in source
    assert "rsl_ticket_events" in source
