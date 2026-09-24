(() => {
const $=s=>document.querySelector(s);
const text=(id,v)=>{const e=$("#"+id);if(e)e.textContent=v==null||v===""?"—":String(v)};
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function api(url){const r=await fetch(url,{credentials:"same-origin"});if(!r.ok)throw new Error(await r.text());return r.json()}
async function load(){
 try{
  const me=await api("/api/me");
  text("profile-name",me.global_name||me.username||"Driver");
  text("profile-discord",me.username?"@"+me.username:"Discord account");
  const guilds=(await api("/api/guilds")).guilds||[];
  const cookie=(document.cookie.match(/(?:^|; )rsl_guild_id=([^;]+)/)||[])[1];
  const guild=(guilds.find(g=>String(g.id)===decodeURIComponent(cookie||""))||guilds[0]);
  if(!guild)throw new Error("No Discord server is available for this account.");
  document.cookie="rsl_guild_id="+encodeURIComponent(guild.id)+";path=/;max-age=2592000;SameSite=Lax";
  const d=await api("/api/player/me?guild_id="+encodeURIComponent(guild.id));
  const p=d.player||{}, prefs=d.preferences||{};
  text("game-name",p.game_name||prefs.game_name||"Not set");
  text("game-id",p.game_id||"Not linked");
  text("platform",p.platform||prefs.platform||"Not set");
  text("driver-type",p.driver_type||prefs.driver_type||"Not set");
  text("location",p.location||prefs.location||"Not set");
  text("timezone",p.timezone||prefs.timezone||"UTC");
  text("about",p.about||prefs.about||"No About Me information added yet.");
  text("elo",Number(p.elo||0).toLocaleString());
  text("wins",p.career_wins??0);
  text("played",p.career_played??0);
  text("streak",p.streak??0);
  text("season",p.season_number??"—");
  const played=Number(p.career_played||0),wins=Number(p.career_wins||0);
  const lb=await api("/api/leaderboard?guild_id="+encodeURIComponent(guild.id)+"&limit=100").catch(()=>({players:[]}));
  const meRow=(lb.players||[]).find(x=>String(x.user_id)===String(p.user_id||me.id||""));
  text("rank",meRow?.competition_rank?"#"+meRow.competition_rank:"—");
  text("registration-status",p.season_registered?"Gauntlet registration: ACTIVE":"Gauntlet registration: NOT REGISTERED");
  const asphalt=p.asphalt_verified===true?"Verified":(p.asphalt_verified===false?"Pending verification":"Not linked");
  text("asphalt-status","Asphalt account status: "+asphalt);
  const links=Array.isArray(p.links)?p.links:(Array.isArray(prefs.links)?prefs.links:[]);
  const box=$("#links");box.textContent="";
  if(!links.length){const span=document.createElement("span");span.className="profile-status";span.textContent="No links added.";box.append(span)}
  else links.slice(0,5).forEach(url=>{try{const u=new URL(url);if(!/^https?:$/.test(u.protocol))return;const a=document.createElement("a");a.href=u.href;a.target="_blank";a.rel="noopener noreferrer";a.textContent=u.hostname.replace(/^www\./,"");box.append(a)}catch(_){}});
  $("#profile-loading").hidden=true;$("#profile-content").hidden=false;
 }catch(e){$("#profile-loading").textContent=e.message||"Unable to load your profile."}
}
load();
})();