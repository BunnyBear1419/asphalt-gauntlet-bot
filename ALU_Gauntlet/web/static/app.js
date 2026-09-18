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
  const board=await api("/api/leaderboard?guild_id="+encodeURIComponent(guild.id)+"&limit=5");
  const rows=$("#leaderboard-list");
  if(rows)rows.innerHTML=(board.players||[]).length
   ?board.players.map((p,i)=>"<div class='leader-row'><span class='leader-rank'>"+(i+1)+"</span><span class='driver-mini'><span class='driver-dot'>🏎</span><strong>"+esc(p.username||p.global_name||p.game_id||"Driver")+"</strong></span><span class='leader-elo'>"+(p.elo??1000).toLocaleString()+"</span></div>").join("")
   :"<p class='empty-state'>No registered drivers yet.</p>";
  const own=(board.players||[]).find(p=>String(p.user_id)===String(me.id)||String(p.user_id)===String(me.user_id));
  if(own){
   const set=(s,v)=>{const x=$(s);if(x)x.textContent=v};
   set("#profile-elo",(own.elo??1000).toLocaleString());set("#profile-pi",Number(own.garage_pi||0).toLocaleString());set("#garage-pi","GARAGE PI "+Number(own.garage_pi||0).toLocaleString());set("#wins",own.career_wins??0);set("#losses",Math.max(0,(own.career_played??0)-(own.career_wins??0)));set("#streak",own.streak??0);
  } else {
   const p=await api("/api/player/me?guild_id="+encodeURIComponent(guild.id)).catch(()=>null);
   if(p&&p.player){const d=p.player;const set=(s,v)=>{const x=$(s);if(x)x.textContent=v};set("#profile-elo",(d.elo??1000).toLocaleString());set("#profile-pi",Number(d.garage_pi||0).toLocaleString());set("#garage-pi","GARAGE PI "+Number(d.garage_pi||0).toLocaleString());set("#wins",d.career_wins??0);set("#losses",Math.max(0,(d.career_played??0)-(d.career_wins??0)));set("#streak",d.streak??0)}
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
 const load=async()=>{if(!sel.value)return;try{const q=encodeURIComponent($("#search")?.value||"");const d=await api("/api/players?guild_id="+encodeURIComponent(sel.value)+"&search="+q);$("#rows").innerHTML=d.players.length?d.players.map(p=>"<tr><td><b>"+esc(p.username||p.user_id||"Unknown")+"</b><small>"+esc(p.game_id||"No game ID")+"</small></td><td>"+(p.elo??1000)+"</td><td>"+Number(p.garage_pi||0).toLocaleString()+"</td><td>"+(p.season_number??"—")+"</td><td>"+(p.career_wins??0)+"-"+Math.max(0,(p.career_played??0)-(p.career_wins??0))+"</td><td>"+(p.defense_locked?"LOCKED":"OPEN")+"</td></tr>").join(""):"<tr><td colspan='6'>No drivers found.</td></tr>"}catch(e){$("#rows").innerHTML="<tr><td colspan='6'>"+esc(e.message)+"</td></tr>"}};
 sel.addEventListener("change",load);$("#refresh")?.addEventListener("click",load);$("#search")?.addEventListener("input",()=>{clearTimeout(window._searchTimer);window._searchTimer=setTimeout(load,250)});await load();
}
window.ALUGauntlet={init:loadDashboard,initPlayers};
document.addEventListener("DOMContentLoaded",()=>{if(location.pathname==="/")loadDashboard()});
