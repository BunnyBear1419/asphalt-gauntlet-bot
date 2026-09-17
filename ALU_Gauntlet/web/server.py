"""Staff-only aiohttp control center shared with the Discord bot."""
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
from .launchcheck import LaunchCheckService
from .logs import LogService
log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).parent / "static"

class WebControlCenter:
    def __init__(self, bot: Any, host: str = "127.0.0.1", port: int = 8080):
        self.bot=bot; self.host=host; self.port=port; self.auth=DiscordOAuth(bot)
        self.players=PlayerService(bot); self.defenses=DefenseService(bot); self.matches=MatchService(bot); self.maps=MapService(bot); self.launchcheck=LaunchCheckService(bot); self.logs=LogService(bot)
        self.app=web.Application(); self.runner=None; self.site=None; self._configure_routes()
    def _configure_routes(self):
        routes={"/":self.index,"/health":self.health,"/players":self.players_page,"/defenses":self.defenses_page,"/matches":self.matches_page,"/seasons":self.seasons_page,"/analytics":self.analytics_page,"/maps":self.maps_page,"/setup":self.setup_page,"/launchcheck":self.launchcheck_page,"/logs":self.logs_page,"/login":self.login,"/auth/callback":self.callback,"/logout":self.logout,"/api/me":self.me,"/api/status":self.status,"/api/guilds":self.guilds,"/api/players":self.player_list,"/api/players/{user_id}":self.player_detail,"/api/defenses":self.defense_list,"/api/defenses/{user_id}":self.defense_detail,"/api/matches":self.match_list,"/api/matches/{match_id}":self.match_detail,"/api/seasons":self.season_list,"/api/seasons/{season_number}":self.season_detail,"/api/analytics":self.analytics,"/api/maps":self.map_list,"/api/maps/{track}":self.map_detail,"/api/setup":self.setup,"/api/launchcheck":self.launchcheck_api,"/api/logs":self.logs_api}
        for path,handler in routes.items(): self.app.router.add_get(path,handler)
        self.app.router.add_static("/static/",WEB_DIR,show_index=False)
    async def health(self,r):
        return web.json_response({"status":"ok","service":"alu-gauntlet-web","port":self.port})
    async def require_staff(self,request):
        if not self.auth.configured: raise web.HTTPServiceUnavailable(text="Web authentication is not configured. Set DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET.")
        user=await self.auth.get_session(request)
        if user is None: raise web.HTTPFound("/login")
        if not user.staff: raise web.HTTPForbidden(text="Staff access is required.")
        return user
    async def require_guild_access(self,request):
        user=await self.require_staff(request); gid=request.query.get("guild_id","").strip()
        if not gid: raise web.HTTPBadRequest(text="guild_id is required.")
        if gid not in user.admin_guild_ids and user.user_id not in self.auth.allowed_staff_ids: raise web.HTTPForbidden(text="You are not an administrator of this Discord server.")
        guild=next((g for g in getattr(self.bot,"guilds",[]) if str(getattr(g,"id",""))==gid),None)
        if guild is None: raise web.HTTPNotFound(text="The bot is not connected to this Discord server.")
        return user,gid,guild
    async def _page(self,request,name): await self.require_staff(request); return web.FileResponse(WEB_DIR/name)
    async def index(self,r): return await self._page(r,"index.html")
    async def players_page(self,r): return await self._page(r,"players.html")
    async def defenses_page(self,r): return await self._page(r,"defenses.html")
    async def matches_page(self,r): return await self._page(r,"matches.html")
    async def seasons_page(self,r): return await self._page(r,"seasons.html")
    async def analytics_page(self,r): return await self._page(r,"analytics.html")
    async def maps_page(self,r): return await self._page(r,"maps.html")
    async def setup_page(self,r): return await self._page(r,"setup.html")
    async def launchcheck_page(self,r): return await self._page(r,"launchcheck.html")
    async def logs_page(self,r): return await self._page(r,"logs.html")
    async def login(self,r):
        if not self.auth.configured: return web.Response(status=503,text="Web authentication is not configured. Set DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET.")
        user=await self.auth.get_session(r)
        if user and user.staff: raise web.HTTPFound("/")
        state=await self.auth.create_state(); raise web.HTTPFound(self.auth.login_url(state))
    async def callback(self,r):
        if not self.auth.configured: raise web.HTTPServiceUnavailable(text="Web authentication is not configured.")
        state=r.query.get("state",""); code=r.query.get("code","")
        if not state or not await self.auth.consume_state(state): raise web.HTTPBadRequest(text="Invalid or expired OAuth state.")
        if not code: raise web.HTTPUnauthorized(text=r.query.get("error","Authorization was cancelled."))
        tokens=await self.auth.exchange_code(code); token=tokens.get("access_token")
        if not token: raise web.HTTPBadGateway(text="Discord did not return an access token.")
        user=await self.auth.build_user(token)
        if not user.staff: raise web.HTTPForbidden(text="Your Discord account does not have staff access.")
        session=await self.auth.create_session(user); response=web.HTTPFound("/"); self.auth.set_session_cookie(response,session); return response
    async def logout(self,r): await self.auth.destroy_session(r); response=web.HTTPFound("/login"); response.del_cookie(SESSION_COOKIE,path="/"); return response
    async def me(self,r):
        u=await self.require_staff(r); return web.json_response({"id":u.user_id,"username":u.username,"global_name":u.global_name,"staff":u.staff})
    async def status(self,r):
        await self.require_staff(r); ready=bool(getattr(self.bot,"is_ready",lambda:False)()); gs=list(getattr(self.bot,"guilds",[]) or []); latency=getattr(self.bot,"latency",None)
        return web.json_response({"bot":{"online":ready,"latency_ms":round(latency*1000,1) if latency is not None else None,"guild_count":len(gs)},"control_center":{"phase":1,"mutations_enabled":False,"simulator_enabled":False}})
    async def guilds(self,r):
        u=await self.require_staff(r); bg={str(getattr(g,"id","")):g for g in getattr(self.bot,"guilds",[])}; allowed=set(u.admin_guild_ids)
        if u.user_id in self.auth.allowed_staff_ids: allowed=set(bg)
        out=[{"id":gid,"name":str(getattr(bg[gid],"name",gid))} for gid in sorted(allowed & bg.keys())]; out.sort(key=lambda x:x["name"].casefold()); return web.json_response({"guilds":out})
    async def player_list(self,r):
        _,gid,_=await self.require_guild_access(r); search=r.query.get("search","")
        try: limit=int(r.query.get("limit","50"))
        except ValueError: raise web.HTTPBadRequest(text="limit must be an integer.")
        return web.json_response({"players":await self.players.list_players(gid,search=search,limit=limit)})
    async def player_detail(self,r):
        _,gid,_=await self.require_guild_access(r); p=await self.players.get_player(gid,r.match_info["user_id"])
        if p is None: raise web.HTTPNotFound(text="Player not found.")
        return web.json_response({"player":p})
    async def defense_list(self,r):
        _,gid,_=await self.require_guild_access(r); status=r.query.get("status","all").strip().lower()
        if status not in {"all","pending","locked","none"}: raise web.HTTPBadRequest(text="status must be all, pending, locked, or none.")
        return web.json_response({"defenses":await self.defenses.list_defenses(gid,status=status)})
    async def defense_detail(self,r):
        _,gid,_=await self.require_guild_access(r); d=await self.defenses.get_defense(gid,r.match_info["user_id"])
        if d is None: raise web.HTTPNotFound(text="Defense record not found.")
        return web.json_response({"defense":d})
    async def match_list(self,r):
        _,gid,_=await self.require_guild_access(r)
        try: limit=int(r.query.get("limit","100"))
        except ValueError: raise web.HTTPBadRequest(text="limit must be an integer.")
        return web.json_response({"matches":await self.matches.list_matches(gid,limit=limit)})
    async def match_detail(self,r):
        _,gid,_=await self.require_guild_access(r); m=await self.matches.get_match(gid,r.match_info["match_id"])
        if m is None: raise web.HTTPNotFound(text="Match not found.")
        return web.json_response({"match":m})
    async def season_list(self,r):
        _,gid,_=await self.require_guild_access(r); state=await self.bot.db.season_state.find_one({"_id":f"guild_{gid}"}) or {}; config=await self.bot.db.settings.find_one({"_id":gid}) or {}; current=self._public_season_state(gid,state,config)
        history=await self.bot.db.season_history.find({"guild_id":gid}).sort("season_number",-1).limit(25).to_list(length=25)
        return web.json_response({"current":current,"history":[self._public_archive(x) for x in history]})
    async def season_detail(self,r):
        _,gid,_=await self.require_guild_access(r)
        try: num=int(r.match_info["season_number"])
        except ValueError: raise web.HTTPBadRequest(text="season_number must be an integer.")
        row=await self.bot.db.season_history.find_one({"_id":f"{gid}_{num}","guild_id":gid})
        if row is None: raise web.HTTPNotFound(text="Season archive not found.")
        return web.json_response({"season":self._public_archive(row,include_standings=True)})
    async def analytics(self,r):
        _,gid,_=await self.require_guild_access(r); players=await self.bot.db.drivers.count_documents({"guild_id":gid}); registered=await self.bot.db.drivers.count_documents({"guild_id":gid,"season_registered":True}); defenses=await self.bot.db.drivers.count_documents({"guild_id":gid,"defense":{"$exists":True}}); matches=await self.bot.db.matches.count_documents({"guild_id":gid}); completed=await self.bot.db.matches.count_documents({"guild_id":gid,"status":"completed"})
        history=await self.bot.db.season_history.find({"guild_id":gid}).sort("season_number",-1).limit(25).to_list(length=25); stats=[]
        for row in history:
            standings=row.get("standings",[]); elos=[int(x.get("elo",1000) or 1000) for x in standings]; stats.append({"season_number":int(row.get("season_number",0) or 0),"player_count":int(row.get("player_count",len(standings)) or 0),"average_elo":round(sum(elos)/len(elos),1) if elos else None,"closed_at":row.get("closed_at")})
        return web.json_response({"players":players,"registered":registered,"defenses":defenses,"matches":matches,"completed_matches":completed,"seasons":stats})
    async def map_list(self,r):
        await self.require_guild_access(r)
        from ..core.core import ALU_TRACKS
        return web.json_response({"maps":await self.maps.list_maps(list(ALU_TRACKS))})
    async def map_detail(self,r):
        await self.require_guild_access(r); from ..core.core import ALU_TRACKS
        track=r.match_info["track"]
        if track not in ALU_TRACKS: raise web.HTTPNotFound(text="Map or route not found.")
        data=await self.maps.get_map(track)
        if data is None: raise web.HTTPNotFound(text="Map or route data not found.")
        return web.json_response({"map":data})
    async def setup(self,r):
        _,gid,_=await self.require_guild_access(r); settings=await self.bot.db.settings.find_one({"_id":gid}) or {}
        keys=("registration_channel_id","review_channel_id","log_channel_id","announcement_channel_id","match_results_channel_id","admin_role_id","player_role_id","timezone")
        return web.json_response({"setup":{key:settings.get(key) for key in keys}})
    async def launchcheck_api(self,r):
        _,gid,_=await self.require_guild_access(r)
        return web.json_response(await self.launchcheck.run(gid))
    async def logs_api(self,r):
        _,gid,_=await self.require_guild_access(r)
        try: limit=int(r.query.get("limit","200"))
        except ValueError: raise web.HTTPBadRequest(text="limit must be an integer.")
        return web.json_response({"logs":await self.logs.list_logs(gid,limit=limit)})
    @staticmethod
    def _public_season_state(gid,state,config): return {"guild_id":gid,"season_number":int(state.get("season_number",1) or 1),"season_active":bool(state.get("season_active",False)),"awaiting_staff_start":bool(state.get("awaiting_staff_start",False)),"starts_at":state.get("starts_at"),"ends_at":state.get("ends_at"),"started_at":state.get("started_at"),"automatic_rollover":bool(config.get("automatic_season_end",False))}
    @staticmethod
    def _public_archive(row,include_standings=False):
        result={"season_number":int(row.get("season_number",0) or 0),"player_count":int(row.get("player_count",len(row.get("standings",[]))) or 0),"closed_at":row.get("closed_at")}
        if include_standings: result["standings"]=[{"rank":x.get("rank"),"user_id":str(x.get("user_id","")),"elo":int(x.get("elo",1000) or 1000),"division":str(x.get("division","Unranked"))} for x in row.get("standings",[])[:100]]
        return result
    async def start(self):
        if self.runner is not None:return
        self.runner=web.AppRunner(self.app); await self.runner.setup(); self.site=web.TCPSite(self.runner,self.host,self.port); await self.site.start(); log.info("Gauntlet web control center listening on http://%s:%s",self.host,self.port)
    async def stop(self):
        if self.runner is None:return
        await self.runner.cleanup(); self.runner=None; self.site=None
