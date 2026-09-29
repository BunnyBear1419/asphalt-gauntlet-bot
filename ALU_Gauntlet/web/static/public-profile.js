(() => {
const $=s=>document.querySelector(s);
const set=(id,v)=>{const e=$("#"+id);if(e)e.textContent=v==null||v===""?"—":String(v)};
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function api(url){const r=await fetch(url,{credentials:"same-origin"});if(!r.ok)throw new Error(await r.text());return r.json()}
async function load(){
 try{
  const userId=new URLSearchParams(location.search).get("user_id");
  if(!userId) throw new Error("No driver was selected.");
  const me=await api("/api/me").catch(()=>null);
  const requestedId=String(userId);
  const effectiveId=requestedId==="me"?(me?.id||""):requestedId;
  if(!effectiveId) throw new Error("No driver was selected.");
  const d=await api("/api/players/"+encodeURIComponent(effectiveId));
  const p=d.player||{};
  const edit=$("#edit-profile"); if(edit&&me&&String(me.id)===String(p.user_id)) edit.hidden=false;
  set("name",p.discord_name||p.username||p.game_name||"Driver");
  set("discord",p.discord_username?"@"+p.discord_username:"RSL Driver");
  const avatar=$("#avatar");
  if(avatar&&p.avatar_url){const img=document.createElement("img");img.src=p.avatar_url;img.alt=(p.discord_name||"Driver")+" RSL avatar";img.onerror=()=>{img.remove()};avatar.textContent="";avatar.append(img)}
  set("game-name",p.game_name||"Not set");
  set("platform",p.platform||"Not set");
  set("driver-type",p.driver_type||"Not set");
  set("location",p.location||"Not set");
  set("about",p.about||"No public About Me information.");
  set("rank",p.competition_rank?"#"+p.competition_rank:"—");
  set("elo",Number.isFinite(Number(p.elo))?Math.trunc(Number(p.elo)).toLocaleString():"1,000");
  set("season",p.season_number||"—");
  set("wins",p.career_wins??0); set("played",p.career_played??0); set("streak",p.streak??0);
  set("registration",p.season_registered?"Gauntlet registration: ACTIVE":"Gauntlet registration: NOT REGISTERED");
  set("xp-level",p.xp_level??1); set("xp-total",Number(p.xp_total||0).toLocaleString()); set("xp-rank",p.xp_rank?"#"+p.xp_rank:"—");
  const links=$("#links"); if(links){links.innerHTML="";const values=Array.isArray(p.links)?p.links:[];if(!values.length){links.textContent="No public links added."}else values.slice(0,5).forEach(url=>{try{const u=new URL(url);if(!/^https?:$/.test(u.protocol))return;const a=document.createElement("a");a.href=u.href;a.target="_blank";a.rel="noopener noreferrer";a.textContent=u.hostname.replace(/^www\./,"");links.append(a)}catch(_){}})}
  $("#loading").hidden=true;$("#content").hidden=false;
 }catch(e){$("#loading").textContent=e.message||"Unable to load this driver profile."}
}
load();
})();