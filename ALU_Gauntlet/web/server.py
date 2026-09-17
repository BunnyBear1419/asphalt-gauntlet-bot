"""Small aiohttp control-center server shared with the Discord bot."""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Any
from aiohttp import web
from .auth import DiscordOAuth, SESSION_COOKIE
from .players import PlayerService
from .defenses import DefenseService
from .matches import MatchService
from .maps import MapService
log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent / "static"
class WebControlCenter:
    def __init__(self, bot: Any, host: str = "127.0.0.1", port: int = 8080) -> None:
        self.bot=bot; self.host=host; self.port=port; self.auth=DiscordOAuth(bot); self.players=PlayerService(bot); self.defenses=DefenseService(bot); self.matches=MatchService(bot); self.maps=MapService(bot); self.app=web.Application(); self.runner=None; self.site=None; self._configure_routes()
    def _configure_routes(self):
        for path, handler in [("/",self.index),("/players",self.players_page),("/defenses",self.defenses_page),("/matches",self.matches_page),("/seasons",self.seasons_page),("/analytics",self.analytics_page),("/maps",self.maps_page),("/login",self.login),("/auth/callback",self.callback),("/logout",self.logout),("/api/me",self.me),("/api/status",self.status),("/api/guilds",self.guilds),("/api/players",self.player_list),("/api/players/{user_id}",self.player_detail),("/api/defenses",self.defense_list),("/api/defenses/{user_id}",self.defense_detail),("/api/matches",self.match_list),("/api/matches/{match_id}",self.match_detail),("/api/seasons",self.season_list),("/api/seasons/{season_number}",self.season_detail),("/api/analytics",self.analytics),("/api/maps",self.map_list),("/api/maps/{track}",self.map_detail)]: self.app.router.add_get(path,handler)
        self.app.router.add_static("/static/",WEB_DIR,show_index=False)
    async def require_staff(self,request):
        if not self.auth.configured: raise web.HTTPServiceUnavailable(text="Web authentication is not configured.")
        user=await self.auth.get_session(request)
        if user is None: raise web.HTTPFound("/login")
        if not user.staff: raise web.HTTPForbidden(text="Staff access is required.")
        return user
    async def require_guild_access(self,request):
        user=await self.require_staff(request); guild_id=request.query.get("guild_id","").strip()
        if not guild_id: raise web.HTTPBadRequest(text="guild_id is required.")
        if guild_id not in user.admin_guild_ids and user.user_id not in self.auth.allowed_staff_ids: raise web.HTTPForbidden(text="You are not an administrator of this Discord server.")
        guild=next((g for g in getattr(self.bot,"guilds",[]) if str(getattr(g,"id",""))==guild_id),None)
        if guild is None: raise web.HTTPNotFound(text="The bot is not connected to this Discord server.")
        return user,guild_id,guild
    async def _page(self,request,name): await self.require_staff(request); return web.FileResponse(WEB_DIR/name)
    async def index(self,r): return await self._page(r,"index.html")
    async def players_page(self,r): return await self._page(r,"players.html")
    async def defenses_page(self,r): return await self._page(r,"defenses.html")
    async def matches_page(self,r): return await self._page(r,"matches.html")
    async def seasons_page(self,r): return await self._page(r,"seasons.html")
    async def analytics_page(self,r): return await self._page(r,"analytics.html")
    async def maps_page(self,r): return await self._page(r,"maps.html")
    async def login(self,request):
        if not self.auth.configured: return web.Response(status=503,text="Web authentication is not configured.")
        user=await self.auth.get_session(request)
        if user and user.staff: raise web.HTTPFound("/")
        state=await self.auth.create_state(); raise web.HTTPFound(self.auth.login_url(state))
    async def callback(self,request):
        if not self.auth.configured: raise web.HTTPServiceUnavailable(text="Web authentication is not configured.")
        state=request.query.get("state",""); code=request.query.get("code","")
        if not state or not await self.auth.consume_state(state): raise web.HTTPBadRequest(text="Invalid or expired OAuth state.")
        if not code: raise web.HTTPUnauthorized(text=request.query.get("error","Authorization was cancelled."))
        tokens=await self.auth.exchange_code(code); access_token=tokens.get("access_token")
        if not access_token: raise web.HTTPBadGateway(text="Discord did not return an access token.")
        user=await self.auth.build_user(access_token)
        if not user.staff: raise web.HTTPForbidden(text="Your Discord account does not have staff access.")
        session=await self.auth.create_session(user); response=web.HTTPFound("/"); self.auth.set_session_cookie(response,session); return response
    async def logout(self,request): await self.auth.destroy_session(request); response=web.HTTPFound("/login"); response.del_cookie(SESSION_COOKIE,path="/"); return response
    async def me(self,r): user=await self.require_staff(r); return web.json_response({"id":user.user_id,"username":user.username,"global_name":user.global_name,"staff":user.staff})
    async def status(self,r):
        await self.require_staff(r); ready=bool(getattr(self.bot,"is_ready",lambda:False)()); guilds=list(getattr(self.bot,"guilds",[]) or []); latency=getattr(self.bot,"latency",None)
        return web.json_response({"bot":{"online":ready,"latency_ms":round(latency*1000,1) if latency is not None else None,"guild_count":len(guilds)},"control_center":{"phase":1,"mutations_enabled":False,"simulator_enabled":False}})
    async def guilds(self,r):
        user=await self.require_staff(r); bg={str(getattr(g,"id","")):g for g in getattr(self.bot,"guilds",[])}; allowed=set(user.admin_guild_ids)
        if user.user_id in self.auth.allowed_staff_ids: allowed=set(bg)
        result=[{"id":i,"name":str(getattr(bg[i],"name",i))} for i in sorted(allowed & bg.keys())]; result.sort(key=lambda x:x["name"].casefold()); return web.json_response({"guilds":result})
    async def player_list(self,r): _,g,_=await self.require_guild_access(r); return web.json_response({"players":await self.players.list_players(g,search=r.query.get("search",""),limit=int(r.query.get("limit","50")))})
    async def player_detail(self,r): _,g,_=await self.require_guild_access(r); p=await self.players.get_player(g,r.match_info["user_id"]); 
    async def defense_list(self,r): _,g,_=await self.require_guild_access(r); return web.json_response({"defenses":await self.defenses.list_defenses(g,status=r.query.get("status","all"))})
    async def defense_detail(self,r): _,g,_=await self.require_guild_access(r); d=await self.defenses.get_defense(g,r.match_info["user_id"]); 
    async def match_list(self,r): _,g,_=await self.require_guild_access(r); return web.json_response({"matches":await self.matches.list_matches(g,limit=int(r.query.get("limit","100")))})
    async def match_detail(self,r): _,g,_=await self.require_guild_access(r); m=await self.matches.get_match(g,r.match_info["match_id"]); 
    async def season_list(self,r): _,g,_=await self.require_guild_access(r); state=await self.bot.db.season_state.find_one({"_id":f"guild_{g}"}) or {}; config=await self.bot.db.settings.find_one({"_id":g}) or {}; return web.json_response({"current":self._public_season_state(g,state,config)})
    async def season_detail(self,r): raise web.HTTPNotFound(text="Season archive not found.")
    async def analytics(self,r): _,g,_=await self.require_guild_access(r); return web.json_response({"players":await self.bot.db.drivers.count_documents({"guild_id":g}),"registered":await self.bot.db.drivers.count_documents({"guild_id":g,"season_registered":True}),"matches":await self.bot.db.matches.count_documents({"guild_id":g})})
    async def map_list(self,r):
        _,g,_=await self.require_guild_access(r)
        from ..core.core import ALU_TRACKS
        return web.json_response({"maps":await self.maps.list_maps(list(ALU_TRACKS))})
    async def map_detail(self,r):
        _,g,_=await self.require_guild_access(r)
        from ..core.core import ALU_TRACKS
        track=r.match_info["track"]
        if track not in ALU_TRACKS: raise web.HTTPNotFound(text="Map or route not found.")
        result=await self.maps.get_map(track)
        if result is None: raise web.HTTPNotFound(text="Map or route data not found.")
        return web.json_response({"map":result})
    @staticmethod
    def _public_season_state(g,s,c): return {"guild_id":g,"season_number":int(s.get("season_number",1) or 1),"season_active":bool(s.get("season_active",False)),"awaiting_staff_start":bool(s.get("awaiting_staff_start",False)),"starts_at":s.get("starts_at"),"ends_at":s.get("ends_at"),"started_at":s.get("started_at"),"automatic_rollover":bool(c.get("automatic_season_end",False))}
    async def start(self):
        if self.runner is not None:return
        self.runner=web.AppRunner(self.app); await self.runner.setup(); self.site=web.TCPSite(self.runner,self.host,self.port); await self.site.start()
    async def stop(self):
        if self.runner is None:return
        await self.runner.cleanup(); self.runner=None; self.site=None
