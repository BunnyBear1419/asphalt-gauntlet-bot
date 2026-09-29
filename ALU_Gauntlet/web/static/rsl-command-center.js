(()=>{const $=s=>document.querySelector(s),esc=v=>String(v??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
async function api(u){const r=await fetch(u,{credentials:"same-origin"});if(!r.ok)throw new Error(await r.text()||"Request failed");return r.json()}
const row=(a,b,c="")=>'<div class="rsl-center-row"><span>'+esc(a)+'</span><strong class="'+esc(c)+'">'+esc(b)+'</strong></div>';
async function init(){
 const me=await api("/api/me"), g=await api("/api/guilds"), guild=(g.guilds||[])[0]; if(!guild)throw Error("No RSL server is available.");
 const gid=encodeURIComponent(guild.id), p=(await api("/api/player/me?guild_id="+gid)).player||{};
 const board=await api("/api/leaderboard?guild_id="+gid+"&limit=100"), players=board.players||[];
 const own=players.find(x=>String(x.user_id)===String(me.id))||p;
 const career=await api("/api/players/"+encodeURIComponent(me.id)+"/career").catch(()=>({}));
 const c=career||{};
 const wins=Number(c.wins??own.career_wins??0), played=Number(c.played??own.career_played??0), xp=Number(c.xp_total??own.rsl_xp??own.activity_xp??0);
 $("#cc-elo").textContent=Number(c.elo??own.elo??1000).toLocaleString();
 $("#cc-rank").textContent=c.current_season_rank?"#"+c.current_season_rank:"—";
 $("#cc-winrate").textContent=(c.win_rate??(played?wins/played*100:0)).toFixed(1)+"%";
 $("#cc-level").textContent=c.xp_level??own.xp_level??"—";
 const notes=[];
 if(!own.season_registered||Number(own.season_number||0)!==Number(board.players?.[0]?.season_number||own.season_number||0))notes.push(["Season registration","Review your current-season registration","rsl-center-warn"]);
 if(!own.defense_locked)notes.push(["Defense","Set or update your 5-course defense","rsl-center-warn"]);
 if(notes.length===0)notes.push(["RSL status","You're caught up on the main driver actions","rsl-center-ok"]);
 $("#cc-notifications").innerHTML=notes.map(x=>row(x[0],x[1],x[2])).join("");
 const badges=[];
 const add=(ok,label)=>{if(ok)badges.push('<span class="rsl-badge">'+esc(label)+'</span>')};
 add(wins>=1,"First Win"); add(wins>=10,"10 Wins"); add(Number(c.race_wins??0)>=50,"50 Race Wins"); add(Number(c.streak??own.streak??0)>=3,"3-Win Streak"); add(Number(c.track_records??0)>=1,"Track Record"); add(Number(c.tournament_record?.events??0)>=1,"Tournament Driver"); add(xp>=5,"XP Bronze"); add(xp>=10,"XP Silver");
 $("#cc-achievements").innerHTML=badges.length?badges.join(""):'<span class="rsl-badge">Your first achievement is waiting.</span>';
 const recent=c.recent_matches||[];
 $("#cc-activity").innerHTML=recent.length?recent.map(m=>row((m.result||"MATCH")+" • "+(m.score||"—"),m.timestamp?new Date(Number(m.timestamp)*1000).toLocaleString():"Recent")).join(""):row("League activity","No completed Gauntlet activity yet");
 const sorted=[...players].sort((a,b)=>Number(b.elo||0)-Number(a.elo||0)), byWins=[...players].sort((a,b)=>Number(b.career_wins||0)-Number(a.career_wins||0)), byStreak=[...players].sort((a,b)=>Number(b.streak||0)-Number(a.streak||0));
 $("#cc-records").innerHTML=[["Highest current ELO",sorted[0]?.elo??"—"],["Most current wins",byWins[0]?.career_wins??"—"],["Longest current streak",byStreak[0]?.streak??"—"]].map(x=>row(x[0],Number(x[1]||0).toLocaleString())).join("");
 const status=await api("/api/status").catch(()=>({bot:{online:false}})); const health=[["Website","ONLINE","rsl-center-ok"],["Discord Bot",status.bot?.online?"ONLINE":"CHECK","status.bot?.online?"rsl-center-ok":"rsl-center-warn"]];
 if(me.staff){const d=await api("/api/admin/diagnostics?guild_id="+gid).catch(()=>null);if(d?.checks)health.push(...d.checks.slice(0,4).map(x=>[x.name,x.ok?"PASS":"FAIL",x.ok?"rsl-center-ok":"rsl-center-bad"]));}
 $("#cc-health").innerHTML=health.map(x=>row(x[0],x[1],x[2])).join("");
 const season=await api("/api/season?guild_id="+gid).catch(()=>null), s=season?.season||{};
 $("#cc-season").innerHTML=[["Season",s.season_number??own.season_number??"—"],["Status",s.status||s.phase||"Active"],["Start",s.start_time?new Date(s.start_time).toLocaleDateString():"—"],["End",s.end_time?new Date(s.end_time).toLocaleDateString():"—"]].map(x=>row(x[0],x[1])).join("");
}
init().catch(e=>{document.querySelectorAll(".rsl-center-list").forEach(x=>x.innerHTML=row("Command Center",e.message,"rsl-center-bad"))})})();