const $=s=>document.querySelector(s);
async function api(url,opts={}){const r=await fetch(url,{credentials:"same-origin",...opts});if(r.redirected){location.href=r.url;return null}if(!r.ok)throw new Error(await r.text()||"Request failed");return r.json()}
function esc(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
function toast(m,bad=false){let x=$("#toast");if(!x){x=document.createElement("div");x.id="toast";document.body.appendChild(x)}x.textContent=m;x.dataset.bad=bad?"1":"0";setTimeout(()=>x.remove(),3500)}
async function loadDashboard(){
 try{
  const me=await api("/api/me");
  const name=me.global_name||me.username||"Driver";
  ["#user-name","#welcome-name","#profile-name"].forEach(s=>{const x=$(s);if(x)x.textContent=name});
  if(me.staff){const settings=$("#side-settings");if(settings)settings.href="/setup"}
  const status=await api("/api/status");
  const g=await api("/api/guilds");
  const guild=(g.guilds||[])[0];
  const server=$("#server-name");if(server&&guild)server.textContent=guild.name;
  if(!guild)throw new Error("No Discord server available");
  const board=await api("/api/leaderboard?guild_id="+encodeURIComponent(guild.id)+"&limit=10");
  const rows=$("#leaderboard-list");
  const renderBoard=(players)=>{
   if(!rows)return;
   rows.innerHTML=players.length
    ?players.map((p,i)=>"<button type='button' class='leader-row competition-row' data-leader-player='"+esc(p.user_id||"")+"'><span class='leader-rank'>"+(i+1)+"</span><span class='driver-mini'><span class='driver-dot'>🏎</span><span><strong>"+esc(p.username||p.global_name||p.game_id||"Driver")+"</strong>"+(p.asphalt_verified?"<em class='verified-badge'>🟢 VERIFIED ASPHALT</em>":"")+"</span></span><span class='leader-elo'>"+(p.elo??1000).toLocaleString()+"</span><span class='leader-pi'>"+Number(p.garage_pi||0).toLocaleString()+"</span><span class='leader-record'>"+(p.career_wins??0)+"-"+Math.max(0,(p.career_played??0)-(p.career_wins??0))+"</span><span class='leader-streak'>"+(p.streak??0)+"</span><span class='leader-defense'>"+(p.defense_locked?"LOCKED":"OPEN")+"</span></button>").join("")
    :"<p class='empty-state'>No registered drivers found.</p>";
   rows.querySelectorAll("[data-leader-player]").forEach(x=>x.addEventListener("click",()=>openPlayerProfile(x.dataset.leaderPlayer)));
  };
  renderBoard(board.players||[]);
  const seasonLabel=$("#competition-season-label");if(seasonLabel)seasonLabel.textContent=(board.players||[])[0]?.season_number?("Season "+(board.players[0].season_number)):"Current season";
  $("#competition-search")?.addEventListener("input",e=>{const q=e.target.value.trim().toLowerCase();renderBoard((board.players||[]).filter(p=>String(p.username||p.global_name||p.game_id||"driver").toLowerCase().includes(q)));});
  const own=(board.players||[]).find(p=>String(p.user_id)===String(me.id)||String(p.user_id)===String(me.user_id));
  if(own){
   const set=(s,v)=>{const x=$(s);if(x)x.textContent=v};
   set("#profile-elo",(own.elo??1000).toLocaleString());set("#profile-pi",Number(own.garage_pi||0).toLocaleString());set("#garage-pi",Number(own.garage_pi||0).toLocaleString());set("#wins",own.career_wins??0);set("#losses",Math.max(0,(own.career_played??0)-(own.career_wins??0)));set("#streak",own.streak??0);
  } else {
   const p=await api("/api/player/me?guild_id="+encodeURIComponent(guild.id)).catch(()=>null);
   if(p&&p.player){const d=p.player;const set=(s,v)=>{const x=$(s);if(x)x.textContent=v};set("#profile-elo",(d.elo??1000).toLocaleString());set("#profile-pi",Number(d.garage_pi||0).toLocaleString());set("#garage-pi",Number(d.garage_pi||0).toLocaleString());set("#wins",d.career_wins??0);set("#losses",Math.max(0,(d.career_played??0)-(d.career_wins??0)));set("#streak",d.streak??0)}
  }
  const season=await api("/api/season?guild_id="+encodeURIComponent(guild.id)).catch(()=>null);
  if(season&&season.season){
   const s=season.season;
   const n=s.season_number??s.number;
   if(n!=null){if($("#season-number"))$("#season-number").textContent=n;if($("#season-number-text"))$("#season-number-text").textContent=n}
   if($("#season-status"))$("#season-status").textContent=(s.status||s.phase||"Active").toString().toLowerCase().includes("active")?"● Active ●":"● "+esc(s.status||s.phase)+" ●";
   if($("#season-dates"))$("#season-dates").textContent=s.start_time&&s.end_time?new Date(s.start_time).toLocaleDateString()+" – "+new Date(s.end_time).toLocaleDateString():"Live season data";
  }
  const pill=$("#system-pill");if(pill)pill.textContent="ONLINE • "+(status.bot.latency_ms??"—")+" ms";
 }catch(e){
  const pill=$("#system-pill");if(pill)pill.textContent="OFFLINE / SIGN IN";
  const list=$("#leaderboard-list");if(list)list.innerHTML="<p class='empty-state'>Sign in to load live competition data.</p>";
  console.error(e);
 }
}
async function initPlayers(){
 const me=await api("/api/me");const g=await api("/api/guilds");const sel=$("#guild");
 if(sel)sel.innerHTML=(g.guilds||[]).map(x=>"<option value='"+esc(x.id)+"'>"+esc(x.name)+(x.admin?" · Staff":"")+"</option>").join("");
 if(!sel)return;
 const load=async()=>{if(!sel.value)return;try{const q=encodeURIComponent($("#search")?.value||"");const d=await api("/api/players?guild_id="+encodeURIComponent(sel.value)+"&search="+q);$("#rows").innerHTML=d.players.length?d.players.map(p=>"<article class='player-directory-card player-directory-row' data-player-id='"+esc(p.user_id)+"' tabindex='0' role='button' aria-label='View "+esc(p.username||p.user_id||"driver")+" profile'><div class='player-card-top'><div class='player-card-avatar'>🏎️</div><div class='player-card-identity'><span class='eyebrow'>DRIVER</span><h3>"+esc(p.username||p.user_id||"Unknown")+"</h3><small>"+esc(p.game_id||"No game ID")+"</small>"+(p.asphalt_verified?"<em class='verified-badge'>🟢 VERIFIED ASPHALT</em>":"")+"</div><span class='player-card-arrow'>↗</span></div><div class='player-card-stats'><div><small>ELO</small><strong>"+(p.elo??1000)+"</strong></div><div><small>PI</small><strong>"+Number(p.garage_pi||0).toLocaleString()+"</strong></div><div><small>RECORD</small><strong>"+(p.career_wins??0)+"-"+Math.max(0,(p.career_played??0)-(p.career_wins??0))+"</strong></div><div><small>DEFENSE</small><strong>"+(p.defense_locked?"LOCKED":"OPEN")+"</strong></div></div><div class='player-card-footer'><span>SEASON "+esc(p.season_number??"—")+"</span><b>VIEW PROFILE →</b></div></article>").join(""):"<div class='directory-empty'>No drivers found.</div>"}catch(e){$("#rows").innerHTML="<div class='directory-empty'>"+esc(e.message)+"</div>"}};
 sel.addEventListener("change",load);$("#refresh")?.addEventListener("click",load);$("#search")?.addEventListener("input",()=>{clearTimeout(window._searchTimer);window._searchTimer=setTimeout(load,250)});await load();
}
window.ALUGauntlet={init:loadDashboard,initPlayers};
document.addEventListener("DOMContentLoaded",()=>{if(location.pathname==="/")loadDashboard()});

function syncPrimaryNav(){
 const path=location.pathname;
 const hash=location.hash;
 document.querySelectorAll(".top-nav nav a").forEach(a=>a.classList.remove("active"));
 const links=[...document.querySelectorAll(".top-nav nav a")];
 let target=null;
 if(hash==="#leaderboard") target=links.find(a=>a.getAttribute("href")==="/#leaderboard");
 else if(hash==="#help") target=links.find(a=>a.getAttribute("href")==="/#help");
 else if(hash==="#gauntlet") target=links.find(a=>a.getAttribute("href")==="/player#gauntlet");
 else if(path==="/players") target=links.find(a=>a.getAttribute("href")==="/players");
 else if(path==="/setup") target=links.find(a=>a.getAttribute("href")==="/setup");
 else if(path==="/player") target=links.find(a=>a.getAttribute("href")==="/player" && !a.getAttribute("href").includes("#"));
 else if(path==="/tournaments") target=links.find(a=>a.getAttribute("href")==="/tournaments" || a.getAttribute("href")==="/tournaments#clubs");
 else if(path==="/") target=links.find(a=>a.getAttribute("href")==="/");
 if(target) target.classList.add("active");
}
document.addEventListener("DOMContentLoaded",syncPrimaryNav);
window.addEventListener("hashchange",syncPrimaryNav);

async function openPlayerProfile(userId){
 try{
  const d=await api("/api/players/"+encodeURIComponent(userId)),p=d.player||{},conn=p.asphalt_connection||{},links=Array.isArray(p.links)?p.links.slice(0,5):[];
  document.querySelector("#public-player-profile")?.remove();
  const o=document.createElement("div");o.id="public-player-profile";o.className="public-profile-overlay";
  const wins=Number(p.career_wins||0),played=Number(p.career_played||0),losses=Math.max(0,played-wins);
  o.innerHTML="<div class='public-profile-backdrop'></div><article class='public-profile glass-panel' role='dialog' aria-modal='true' aria-labelledby='public-player-title'><button class='public-profile-close qa qa-blue' type='button' aria-label='Close profile'>✕</button>"+
  "<div class='public-profile-hero unified-profile-hero'><div class='public-profile-avatar'>🏎️</div><div><span class='eyebrow'>DRIVER PROFILE</span><h2 id='public-player-title'>"+esc(p.discord_name||p.username||"Driver")+"</h2><p>"+esc(p.game_name||conn.game_name||"Asphalt driver")+"</p>"+(p.asphalt_verified?"<em class='verified-badge'>🟢 VERIFIED ASPHALT</em>":"")+"</div></div>"+
  "<div class='unified-profile-stats'><div><small>ELO</small><strong>"+(p.elo??1000)+"</strong></div><div><small>PI</small><strong>"+Number(p.garage_pi||0).toLocaleString()+"</strong></div><div><small>RECORD</small><strong>"+wins+"-"+losses+"</strong></div><div><small>SEASON</small><strong>"+esc(p.season_number??"—")+"</strong></div></div>"+
  "<div class='unified-profile-content'><div class='unified-profile-main'>"+
  "<section class='unified-profile-section'><span class='eyebrow'>ASPHALT IDENTITY</span><div class='unified-profile-info-grid'><div><small>GAME NAME</small><strong>"+esc(p.game_name||conn.game_name||"Not set")+"</strong></div><div><small>GAME ID</small><strong>"+esc(p.game_id||conn.game_id||"Not set")+"</strong></div><div><small>LOCATION</small><strong>"+esc(p.location||"Not set")+"</strong></div><div><small>TIMEZONE</small><strong>"+esc(p.timezone_label||p.timezone||"UTC")+"</strong></div></div></section>"+
  "<section class='unified-profile-section'><span class='eyebrow'>ABOUT ME</span><p>"+esc(p.about||"No bio added yet.")+"</p></section>"+
  (links.length?"<section class='unified-profile-section'><span class='eyebrow'>LINKS</span><div class='unified-profile-links'>"+links.map((x,i)=>"<a href='"+esc(x)+"' target='_blank' rel='noopener noreferrer'><span>LINK "+(i+1)+"</span><b>"+esc(x.replace(/^https?:\/\//,"").replace(/\/$/,""))+"</b>↗</a>").join("")+"</div></section>":"")+
  "</div><aside class='unified-profile-side'><span class='eyebrow'>COMPETITION</span><div class='profile-side-card'><small>DEFENSE</small><strong>"+(p.defense_locked?"LOCKED":"OPEN")+"</strong></div><div class='profile-side-card'><small>STREAK</small><strong>"+(p.streak??0)+"</strong></div><div class='profile-side-card'><small>CAREER WINS</small><strong>"+wins+"</strong></div></aside></div></article>";
  document.body.appendChild(o);
  const close=()=>o.remove();
  o.querySelector(".public-profile-close").addEventListener("click",close);
  o.querySelector(".public-profile-backdrop").addEventListener("click",close);
  const handler=e=>{if(e.key==="Escape"){close();document.removeEventListener("keydown",handler)}};document.addEventListener("keydown",handler);
 }catch(e){toast(e.message,true)}
}
document.addEventListener("DOMContentLoaded",()=>{const rows=$("#rows");if(!rows)return;rows.addEventListener("click",e=>{const r=e.target.closest(".player-directory-row");if(r)openPlayerProfile(r.dataset.playerId)});rows.addEventListener("keydown",e=>{const r=e.target.closest(".player-directory-row");if(r&&(e.key==="Enter"||e.key===" ")){e.preventDefault();openPlayerProfile(r.dataset.playerId)}})});
