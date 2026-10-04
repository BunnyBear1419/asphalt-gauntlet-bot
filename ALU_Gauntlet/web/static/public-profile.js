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
  const [d,career]=await Promise.all([api("/api/players/"+encodeURIComponent(effectiveId)),api("/api/players/"+encodeURIComponent(effectiveId)+"/career")]);
  const p=d.player||{};
  const edit=$("#edit-profile"); if(edit&&me&&String(me.id)===String(p.user_id)) edit.hidden=false;
  set("name",p.discord_name||p.username||p.game_name||"Driver");
  set("discord",p.discord_username?"@"+p.discord_username:"Discord member");
  const avatar=$("#avatar");
  if(avatar){
   avatar.textContent=String(p.discord_name||"Driver").trim().slice(0,1).toUpperCase()||"R";
   const avatarUrl=p.avatar_url||p.discord_avatar_url;
   if(avatarUrl){
    const img=document.createElement("img");
    img.src=avatarUrl;
    img.alt=(p.discord_name||"Driver")+" RSL avatar";
    img.onerror=()=>{img.remove()};
    avatar.textContent="";
    avatar.append(img);
   }
  }
  set("game-name",p.game_name||"Not set");
  set("platform",p.platform||"Not set");
  set("driver-type",p.driver_type||"Not set");
  set("location",p.location||"Not set");
  set("about",p.about||"No public About Me information.");
  const cardDivision=p.division||p.gauntlet_division||p.current_division||"Unranked";
  set("rsl-card-division",cardDivision);
  set("rsl-card-rank",p.competition_rank?"RANK #"+p.competition_rank:"RANK —");
  set("rsl-card-elo",Number.isFinite(Number(p.elo))?Math.trunc(Number(p.elo)).toLocaleString():"1,000");
  const cardWins=Number(p.career_wins||0),cardPlayed=Number(p.career_played||0);
  set("rsl-card-record",cardWins+"-"+Math.max(0,cardPlayed-cardWins));
  set("rsl-card-winrate",cardPlayed?((cardWins/cardPlayed)*100).toFixed(1)+"%":"—");
  set("rank",p.competition_rank?"#"+p.competition_rank:"—");
  set("elo",Number.isFinite(Number(p.elo))?Math.trunc(Number(p.elo)).toLocaleString():"1,000");
  set("season",p.season_number||"—");
  set("wins",p.career_wins??0); set("played",p.career_played??0); set("streak",p.streak??0);
  set("registration",p.season_registered?"Gauntlet registration: ACTIVE":"Gauntlet registration: NOT REGISTERED");
  set("xp-level",p.xp_level??1); set("xp-total",Number(p.xp_total||0).toLocaleString()); set("xp-rank",p.xp_rank?"#"+p.xp_rank:"—");
  const g=career.gauntlet||{}, ts=career.tournament_summary||{};
  set("gauntlet-win-rate",Number(g.win_rate||0).toFixed(1)+"%");
  set("race-record",Number(g.race_wins||0)+"-"+Number(g.race_losses||0));
  set("season-points",Number(g.season_points||0).toLocaleString());
  set("track-records",Number(g.track_records||0));
  set("tournament-events",Number(ts.events||0));
  set("tournament-record",Number(ts.wins||0)+"-"+Number(ts.losses||0));
  const buckets=g.score_buckets||{}; set("gauntlet-score-buckets","Match score distribution: 5-0 "+(buckets["5-0"]||0)+" • 4-1 "+(buckets["4-1"]||0)+" • 3-2 "+(buckets["3-2"]||0)+" • 2-3 "+(buckets["2-3"]||0)+" • 1-4 "+(buckets["1-4"]||0)+" • 0-5 "+(buckets["0-5"]||0));
  const history=Array.isArray(career.season_history)?career.season_history:[];
  const historyEl=$("#season-history"); if(historyEl){historyEl.innerHTML=history.length?history.map(x=>'<div class="public-profile-history-row"><strong>Season '+esc(x.season_number)+'</strong><span>Rank '+esc(x.rank||"—")+'</span><span>'+esc(x.wins)+'-'+esc(x.losses)+'</span><span>'+esc(x.points)+' pts</span></div>').join(""):'<p class="empty-state">No archived season results yet.</p>'}
  const records=career.rsl_records||{}, recordsEl=$("#rsl-records"); if(recordsEl){recordsEl.innerHTML='<div class="public-profile-history-row"><strong>Highest ELO</strong><span>'+esc(Number(records.highest_elo||1000).toLocaleString())+'</span><span></span><span></span></div><div class="public-profile-history-row"><strong>Most Career Wins</strong><span>'+esc(records.most_career_wins||0)+'</span><span></span><span></span></div><div class="public-profile-history-row"><strong>Longest Current Streak</strong><span>'+esc(records.longest_current_streak||0)+'</span><span></span><span></span></div><div class="public-profile-history-row"><strong>Most Season Points</strong><span>'+esc(records.most_season_points||0)+'</span><span></span><span></span></div>'}
  const timeline=$("#activity-timeline");
  if(timeline){
   try{
    const t=await api("/api/players/"+encodeURIComponent(effectiveId)+"/activity");
    const events=Array.isArray(t.events)?t.events:[];
    timeline.innerHTML=events.length?events.map(x=>'<div class="public-profile-history-row"><strong>'+esc(x.title)+'</strong><span>'+esc(x.detail||"")+'</span><span>'+esc(x.kind||"")+'</span><span>'+esc(x.timestamp?new Date(Number(x.timestamp)*1000).toLocaleDateString():"—")+'</span></div>').join(""):'<p class="empty-state">No recent public activity yet.</p>';
   }catch(_){timeline.innerHTML='<p class="empty-state">Activity timeline is temporarily unavailable.</p>'}
  }
  const recent=$("#recent-gauntlet"); if(recent){const rows=Array.isArray(g.recent_matches)?g.recent_matches:[];recent.innerHTML=rows.length?rows.map(x=>{const oid=String(x.opponent_id||"");const label=x.result==="WIN"?"WIN":"LOSS";const who=oid?'<a href="/profile?user_id='+encodeURIComponent(oid)+'">View opponent</a>':"Opponent";return '<div class="public-profile-history-row"><strong>'+label+'</strong><span>'+esc(x.score)+'</span><span>'+who+'</span><span>'+esc(x.timestamp?new Date(Number(x.timestamp)*1000).toLocaleDateString():"—")+'</span></div>'}).join(""):'<p class="empty-state">No completed Gauntlet matches yet.</p>'}
  const tournamentHistory=$("#tournament-history"); if(tournamentHistory){const rows=Array.isArray(career.tournaments)?career.tournaments:[];tournamentHistory.innerHTML=rows.length?rows.map(t=>'<div class="public-profile-history-row"><strong>'+esc(t.name)+'</strong><span>'+esc(t.format)+'</span><span>'+esc(t.record)+'</span><span>'+esc(t.status)+'</span></div>').join(""):'<p class="empty-state">No tournament records yet.</p>'}
  const links=$("#links"); if(links){links.innerHTML="";const values=Array.isArray(p.links)?p.links:[];if(!values.length){links.textContent="No public links added."}else values.slice(0,5).forEach(url=>{try{const u=new URL(url);if(!/^https?:$/.test(u.protocol))return;const a=document.createElement("a");a.href=u.href;a.target="_blank";a.rel="noopener noreferrer";a.textContent=u.hostname.replace(/^www\./,"");links.append(a)}catch(_){}})}
  $("#loading").hidden=true;$("#content").hidden=false;
 }catch(e){$("#loading").textContent=e.message||"Unable to load this driver profile."}
}
load();
})();