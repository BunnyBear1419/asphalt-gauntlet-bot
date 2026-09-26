"""Mongo-backed player read service for the web control center."""
from __future__ import annotations
from typing import Any
import re
class PlayerService:
    def __init__(self, bot: Any) -> None: self.bot = bot
    async def get_player(self, guild_id: str, user_id: str):
        row=await self.bot.db.drivers.find_one({"_id":f"{guild_id}_{user_id}"})
        if not row:return None
        return self._safe(dict(row))
    async def list_players(self,guild_id:str,search:str="",limit:int=50):
        q={"guild_id":str(guild_id)}
        if search.strip():
            t=re.escape(search.strip()); q["$or"]=[{"game_id":{"$regex":t,"$options":"i"}},{"user_id":{"$regex":t,"$options":"i"}},{"username":{"$regex":t,"$options":"i"}}]
        rows=await self.bot.db.drivers.find(q).sort("elo",-1).to_list(length=max(1,min(100,int(limit))))
        return [self._safe(dict(x),True) for x in rows]
    @staticmethod
    def _safe(row,include_id=False):
        if include_id: row["id"]=str(row.pop("_id",""))
        else: row.pop("_id",None)
        allowed={"id","guild_id","user_id","username","global_name","game_id","elo","garage_pi","season_registered","season_number","streak","career_wins","career_played","defense_locked","game_name","about","location","links","created_at","updated_at","rsl_dominance","gauntlet_recent_opponents","top_five_car_ranks"}
        return {k:v for k,v in row.items() if k in allowed}
