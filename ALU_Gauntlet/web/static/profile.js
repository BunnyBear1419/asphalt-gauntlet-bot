(() => {
const $=s=>document.querySelector(s);
const text=(id,v)=>{const e=$("#"+id);if(e)e.textContent=v==null||v===""?"—":String(v)};
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function api(url){const r=await fetch(url,{credentials:"same-origin"});if(!r.ok)throw new Error(await r.text());return r.json()}
async function load(){
 try{
  const me=await api("/api/me");
  const discordName=me.global_name||me.username||"Driver";
  text("profile-name",discordName);
  const avatarBox=$(".profile-avatar-large");
  if(avatarBox){
    const avatarUrl=me.id&&me.avatar?"https://cdn.discordapp.com/avatars/"+encodeURIComponent(me.id)+"/"+encodeURIComponent(me.avatar)+".png?size=256":(me.id?"https://cdn.discordapp.com/embed/avatars/"+(Number(BigInt(me.id)%7n))+".png":"");
    if(avatarUrl){const img=document.createElement("img");img.src=avatarUrl;img.alt=discordName+" Discord avatar";avatarBox.textContent="";avatarBox.appendChild(img);}
  }
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
  const tourney=await api("/api/profile/tournaments").catch(()=>({stats:{},upcoming:[],history:[]}));
  const ts=tourney.stats||{};
  text("tourney-entered",ts.entered??0); text("tourney-completed",ts.completed??0); text("tourney-played",ts.matches_played??0);
  text("tourney-wins",ts.wins??0); text("tourney-losses",ts.losses??0); text("tourney-rate",(ts.win_rate??0)+"%");
  const currentBox=$("#tourney-current"), active=(tourney.upcoming||[]).filter(t=>["live","registration_open","open"].includes(t.status));
  if(currentBox){currentBox.textContent=active.length?active.slice(0,3).map(t=>t.name+" • "+(t.status==="live"?"Live":"Registered/Open")+(t.team_size>1?" • "+t.team_size+"v"+t.team_size:"")).join("\n"):"No active tournament registrations.";currentBox.style.whiteSpace="pre-line";}
  const historyBox=$("#tourney-history");
  if(historyBox){historyBox.innerHTML="";const history=tourney.history||[];if(!history.length){const e=document.createElement("div");e.className="profile-status";e.textContent="No completed tournament history yet.";historyBox.append(e);}else history.forEach(t=>{const row=document.createElement("div");row.className="profile-field";row.style.marginBottom="10px";row.innerHTML="<strong>"+esc(t.name)+"</strong><span style=\"display:block;margin-top:6px;color:#7188a7;font-size:11px\">"+esc(t.format_label)+(t.team_size>1?" • "+t.team_size+"v"+t.team_size:"")+" • "+esc(t.finish)+" • "+Number(t.wins||0)+"W-"+Number(t.losses||0)+"L • "+Number(t.matches_played||0)+" matches</span>";historyBox.append(row);});}
  const links=Array.isArray(p.links)?p.links:(Array.isArray(prefs.links)?prefs.links:[]);
  const box=$("#links");box.textContent="";
  if(!links.length){const span=document.createElement("span");span.className="profile-status";span.textContent="No links added.";box.append(span)}
  else links.slice(0,5).forEach(url=>{try{const u=new URL(url);if(!/^https?:$/.test(u.protocol))return;const a=document.createElement("a");a.href=u.href;a.target="_blank";a.rel="noopener noreferrer";a.textContent=u.hostname.replace(/^www\./,"");box.append(a)}catch(_){}});
  $("#profile-loading").hidden=true;$("#profile-content").hidden=false;
 }catch(e){$("#profile-loading").textContent=e.message||"Unable to load your profile."}
}
load();
})();