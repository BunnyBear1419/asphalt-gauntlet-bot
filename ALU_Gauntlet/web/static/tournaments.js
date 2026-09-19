const $=s=>document.querySelector(s);
async function api(url,opts={}){const r=await fetch(url,{credentials:"same-origin",...opts});if(r.redirected){location.href=r.url;return null}if(!r.ok)throw new Error(await r.text()||"Request failed");return r.json()}
function esc(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
function toast(m,bad=false){let x=$("#toast");if(!x){x=document.createElement("div");x.id="toast";document.body.appendChild(x)}x.textContent=m;x.dataset.bad=bad?"1":"0";setTimeout(()=>x.remove(),3500)}
function statusLabel(s){return ({registration_open:"REGISTRATION OPEN",open:"REGISTRATION OPEN",live:"LIVE",completed:"COMPLETED",draft:"DRAFT"})[s]||String(s||"DRAFT").replaceAll("_"," ").toUpperCase()}
function clubHtml(t){if(Number(t.team_size||1)<=1)return "";const teams=t.teams||[];if(!teams.length)return '<section class="club-panel"><h3>Create Your Club</h3><p>Build a roster of up to 20 members, then use 2v2, 3v3 or 4v4 lineups.</p><button class="qa qa-purple" id="create-club">Create Club</button></section>';return '<section class="club-panel"><div class="panel-heading"><h3>Clubs</h3><span>Up to 20 members</span></div>'+teams.map(team=>'<article class="club-card"><div class="club-avatar">'+(team.image?'<img src="'+esc(team.image)+'" alt="">':'🏁')+'</div><div class="club-main"><h4>'+esc(team.name)+'</h4><p>'+esc(team.about||"ALU tournament club")+'</p><small>'+team.members.length+'/20 members</small><div class="club-members">'+team.members.map(m=>'<span>'+esc(m.username)+' · '+esc(m.role)+'</span>').join("")+'</div></div></article>').join("")+'</section>'}\nfunction verifiedBadge(x){return x?.verified ? '<em class="verified-badge">🟢 VERIFIED ASPHALT</em>' : ""}
function entrantInfo(t,id){
  const sid=String(id||"");
  if(Number(t.team_size||1)>1){
    const club=(t.clubs||[]).find(x=>String(x.id)===sid);
    if(!club)return {name:sid,detail:"Club"};
    const lineup=new Set((club.lineup||[]).map(String));
    const names=(club.members||[]).filter(m=>lineup.has(String(m.user_id))).map(m=>m.username).slice(0,4);
    return {name:club.name,detail:names.length?names.join(" • "):"Lineup not saved",image:club.image||"",verified:club.lineup?.length ? (club.members||[]).filter(m=>club.lineup.map(String).includes(String(m.user_id))).every(m=>m.asphalt_verified) : false,clubId:club.id,identityType:"club"};
  }
  const reg=(t.registrations||[]).find(x=>String(x.user_id)===sid);
  return {name:reg?.username||sid,detail:reg?.asphalt_game_name?("🏎️ "+reg.asphalt_game_name):"Driver",verified:!!reg?.asphalt_verified,userId:reg?.user_id||sid,identityType:"player"};
}
function allMatches(b){
  return (b?.rounds||b?.winners||[]).flatMap(r=>r.matches||[]);
}
function bracketText(t){
  const b=t.bracket;
  if(!b)return '<div class="tournament-empty">Bracket not generated.</div>';
  const groups=b.rounds||b.winners||[];
  return groups.map(r=>'<div class="bracket-round"><h4>'+esc(r.name||("Round "+r.round))+'</h4>'+
    (r.matches||[]).map(m=>{
      const a=entrantInfo(t,m.player_slots?.[0]), z=entrantInfo(t,m.player_slots?.[1]);
      const pending=m.result_status==="pending";
      return '<div class="bracket-match tournament-match" data-match="'+esc(m.id)+'"><button type="button" class="tournament-competitor '+(a.identityType==="club"?"club-competitor":"player-competitor")+'" data-identity-type="'+esc(a.identityType||"")+'" data-identity-id="'+esc(a.identityType==="club"?a.clubId:(a.userId||""))+'" '+(!a.name||a.name==="TBD"?"disabled":"")+'><strong>'+esc(a.name||"TBD")+'</strong><small>'+esc(a.detail||"Waiting")+'</small>'+verifiedBadge(a)+'</button><b>VS</b><button type="button" class="tournament-competitor '+(z.identityType==="club"?"club-competitor":"player-competitor")+'" data-identity-type="'+esc(z.identityType||"")+'" data-identity-id="'+esc(z.identityType==="club"?z.clubId:(z.userId||""))+'" '+(!z.name||z.name==="TBD"?"disabled":"")+'><strong>'+esc(z.name||"TBD")+'</strong><small>'+esc(z.detail||"Waiting")+'</small>'+verifiedBadge(z)+'</button>'+
        (pending?'<span class="match-status">PENDING REVIEW</span>':m.status==="completed"?'<span class="match-status">VERIFIED</span>':m.status==="ready"?'<button class="qa qa-purple match-result" data-match="'+esc(m.id)+'">Submit Result</button>':'')+
        '</div>';
    }).join('')+'</div>').join('')+
    (b.losers?b.losers.map(r=>'<div class="bracket-round"><h4>'+esc(r.name)+'</h4>'+((r.matches||[]).map(m=>'<div class="bracket-match"><span>TBD</span><b>VS</b><span>TBD</span></div>').join(''))+'</div>').join(''):'')+
    (b.grand_final?'<div class="bracket-round"><h4>Grand Final</h4><div class="bracket-match"><span>TBD</span><b>VS</b><span>TBD</span></div></div>':'');
}
async function openTournamentClubProfile(clubId){
  try{
    const data=await api("/api/clubs"),c=(data.clubs||[]).find(x=>String(x.id)===String(clubId));
    if(!c)throw new Error("Club profile not found.");
    document.querySelector("#tournament-club-profile")?.remove();
    const x=document.createElement("div");x.id="tournament-club-profile";x.className="public-profile-overlay";
    const members=c.members||[],verified=members.filter(m=>m.asphalt_verified).length;
    x.innerHTML="<div class='public-profile-backdrop'></div><article class='public-profile glass-panel tournament-club-profile' role='dialog' aria-modal='true'><button class='public-profile-close qa qa-blue' type='button' aria-label='Close club profile'>✕</button><div class='public-profile-hero unified-profile-hero'><div class='public-profile-avatar'>"+(c.image?"<img src='"+esc(c.image)+"' alt=''>":"🏁")+"</div><div><span class='eyebrow'>CLUB PROFILE</span><h2>"+esc(c.name)+"</h2><p>"+esc(c.about||"ALU competitive club")+"</p><em class='verified-badge'>"+verified+"/"+members.length+" VERIFIED ASPHALT</em></div></div><div class='unified-profile-stats'><div><small>MEMBERS</small><strong>"+members.length+"/20</strong></div><div><small>TOURNAMENTS</small><strong>"+Number(c.tournament_count||0)+"</strong></div><div><small>PENDING</small><strong>"+Number(c.tournament_pending_count||0)+"</strong></div><div><small>ACCEPTED</small><strong>"+Number(c.tournament_accepted_count||0)+"</strong></div></div><div class='unified-profile-content'><div class='unified-profile-main'><section class='unified-profile-section'><span class='eyebrow'>ROSTER</span><div class='tournament-club-roster'>"+(members.length?members.map(m=>"<button type='button' class='tournament-club-driver' data-player-id='"+esc(m.user_id)+"'><strong>"+esc(m.username||m.user_id)+"</strong><small>"+esc(m.role||"Driver")+"</small>"+(m.asphalt_verified?"<em class='verified-badge'>🟢 VERIFIED ASPHALT</em>":"")+"</button>").join(""):"<p>No members yet.</p>")+"</div></section></div><aside class='unified-profile-side'><span class='eyebrow'>CLUB</span><div class='profile-side-card'><small>LEADER</small><strong>"+esc(members.find(m=>String(m.user_id)===String(c.leader_id))?.username||"Club Leader")+"</strong></div><div class='profile-side-card'><small>TEAM FORMATS</small><strong>2v2 · 3v3 · 4v4</strong></div></aside></div></article>";
    document.body.appendChild(x);
    const close=()=>x.remove();x.querySelector(".public-profile-close").onclick=close;x.querySelector(".public-profile-backdrop").onclick=close;
    x.querySelectorAll(".tournament-club-driver").forEach(b=>b.onclick=()=>openPlayerProfile(b.dataset.playerId));
    const h=e=>{if(e.key==="Escape"){close();document.removeEventListener("keydown",h)}};document.addEventListener("keydown",h);
  }catch(e){toast(e.message,true)}
}
function resultDialog(t,match){
  const slots=(match.player_slots||[]).filter(Boolean).map(String);
  const choices=slots.map(id=>{const x=entrantInfo(t,id);return '<option value="'+esc(id)+'">'+esc(x.name)+(x.verified?" • ✓ Verified":"")+'</option>'}).join('');
  const wrap=document.createElement("div");wrap.className="club-picker-overlay";
  wrap.innerHTML='<div class="club-picker glass-panel"><span class="eyebrow">MATCH RESULT</span><h2>Submit Match Result</h2><p>Choose the winner. Staff will verify the result before the bracket advances.</p><label>Winner<select id="result-winner">'+choices+'</select></label><label>Proof URL (optional)<input id="result-proof" placeholder="https://..."></label><label>Notes (optional)<textarea id="result-notes" maxlength="500" placeholder="Score, race notes, or other details"></textarea></label><div class="club-picker-actions"><button class="qa qa-blue" id="result-cancel">Cancel</button><button class="qa qa-purple" id="result-send">Submit Result →</button></div></div>';
  document.body.appendChild(wrap);
  return new Promise(resolve=>{const close=v=>{wrap.remove();resolve(v)};wrap.querySelector("#result-cancel").onclick=()=>close(null);wrap.querySelector("#result-send").onclick=()=>close({winner_id:wrap.querySelector("#result-winner").value,proof_url:wrap.querySelector("#result-proof").value.trim(),notes:wrap.querySelector("#result-notes").value.trim()})});
}
async function submitResult(t,match){
  try{
    const data=await resultDialog(t,match); if(!data)return;
    const r=await api("/api/tournaments/result",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({tournament_id:t.id,match_id:match.id,...data})});
    toast(r.message||"Result submitted."); await showTournament(t.id);
  }catch(e){toast(e.message,true)}
}
async function verifyResult(t,match,action,button){
  if(button?.disabled)return;
  const original=button?.textContent;
  if(button){button.disabled=true;button.textContent=action==="approve"?"Approving…":"Rejecting…"}
  try{
    const r=await api("/api/tournaments/result/verify",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({tournament_id:t.id,match_id:match.id,action})});
    toast(r.message||"Result updated."); await showTournament(t.id);
  }catch(e){toast(e.message,true)}finally{if(button){button.disabled=false;button.textContent=original}}
}
async function checkin(id,button){
  if(button?.disabled)return;
  const original=button?.textContent;
  if(button){button.disabled=true;button.textContent="Checking In…"}
  try{const r=await api("/api/tournaments/checkin",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({tournament_id:id})});toast(r.message||"Checked in.");await showTournament(id)}catch(e){toast(e.message,true)}finally{if(button){button.disabled=false;button.textContent=original}}
}
async function showTournament(id){
  try{
    const t=await api("/api/tournaments/"+encodeURIComponent(id)); const box=$("#tournament-detail"); box.hidden=false;
    const pending=allMatches(t.bracket).filter(m=>m.result_status==="pending" && m.winner_id);
    const champion=t.champion_id?entrantInfo(t,t.champion_id):null;
    box.innerHTML='<div class="panel-heading"><h2>'+esc(t.name)+'</h2><button class="qa qa-blue" id="close-tournament-detail">Close</button></div>'+
      '<p>'+esc(t.description||"")+'</p>'+
      (t.status==="completed"&&champion?'<section class="tournament-champion"><span>🏆 TOURNAMENT CHAMPION</span><button type="button" class="tournament-champion-link" data-identity-type="'+esc(champion.identityType||"")+'" data-identity-id="'+esc(champion.identityType==="club"?champion.clubId:(champion.userId||""))+'"><strong>'+esc(champion.name)+'</strong><small>'+esc(champion.detail||"")+'</small>'+verifiedBadge(champion)+'</button></section>':'')+
      '<div class="tournament-detail-actions"><button class="qa qa-purple" id="checkin-tournament">Check In</button></div>'+
      (pending.length&&window._me?.staff?'<section class="match-review glass-panel"><div class="panel-heading"><h3>Staff Result Review</h3><span>'+pending.length+' pending</span></div>'+pending.map(m=>{const w=entrantInfo(t,m.winner_id);return '<div class="review-row"><div><strong>'+esc(m.id)+'</strong><span>Winner submitted: '+esc(w.name)+'</span></div><div><button class="qa qa-purple verify-result" data-match="'+esc(m.id)+'">Approve</button><button class="qa qa-blue reject-result" data-match="'+esc(m.id)+'">Reject</button></div></div>'}).join('')+'</section>':'')+      (Number(t.team_size||1)>1&&((t.clubs||[]).filter(c=>String(c.leader_id)===String(window._me?.id)).length)?'<section class="match-review glass-panel"><div class="panel-heading"><h3>🏎️ Tournament Lineup</h3><span>'+Number(t.team_size||1)+' drivers required</span></div>'+((t.clubs||[]).filter(c=>String(c.leader_id)===String(window._me?.id)).map(c=>'<div class="lineup-editor"><strong>'+esc(c.name)+'</strong><div class="lineup-list">'+(c.members||[]).map(m=>'<label><input class="lineup-member" data-club="'+esc(c.id)+'" type="checkbox" value="'+esc(m.user_id)+'" '+((c.lineup||[]).map(String).includes(String(m.user_id))?'checked':'')+'> '+esc(m.username)+'</label>').join('')+'</div><button class="qa qa-purple lineup-save" data-club="'+esc(c.id)+'">Save Lineup</button></div>').join(''))+'</section>':'')+
      '<div class="tournament-bracket">'+bracketText(t)+'</div>'+clubHtml(t);
    $("#close-tournament-detail").onclick=()=>box.hidden=true; $("#checkin-tournament").onclick=()=>checkin(id);
    box.querySelectorAll(".tournament-competitor").forEach(b=>{b.onclick=()=>{const type=b.dataset.identityType,id=b.dataset.identityId;if(!id)return;if(type==="player")openPlayerProfile(id);else if(type==="club"){openTournamentClubProfile(id)}}});
    box.querySelectorAll(".tournament-champion-link").forEach(b=>{b.onclick=()=>{const type=b.dataset.identityType,id=b.dataset.identityId;if(type==="player")openPlayerProfile(id);else if(type==="club"){openTournamentClubProfile(id)}}});
    const matches=allMatches(t.bracket);
    box.querySelectorAll(".match-result").forEach(b=>{b.onclick=()=>{const m=matches.find(x=>String(x.id)===b.dataset.match);if(m)submitResult(t,m)}});
    box.querySelectorAll(".verify-result").forEach(b=>{b.onclick=()=>{const m=matches.find(x=>String(x.id)===b.dataset.match);if(m)verifyResult(t,m,"approve",b)}});
    box.querySelectorAll(".reject-result").forEach(b=>{b.onclick=()=>{const m=matches.find(x=>String(x.id)===b.dataset.match);if(m)verifyResult(t,m,"reject",b)}});
    box.querySelectorAll(".lineup-save").forEach(b=>{b.onclick=async()=>{if(b.disabled)return;const original=b.textContent;b.disabled=true;b.textContent="Saving…";
      const club=(t.clubs||[]).find(x=>String(x.id)===b.dataset.club); if(!club)return;
      const selected=[...box.querySelectorAll('.lineup-member[data-club="'+CSS.escape(b.dataset.club)+'"]:checked')].map(x=>x.value);
      if(selected.length!==Number(t.team_size||1)){toast("Select exactly "+Number(t.team_size||1)+" drivers.",true);return}
      try{const r=await api("/api/tournaments/clubs/lineup",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({tournament_id:t.id,club_id:club.id,lineup:selected})});toast(r.message||"Lineup saved.");await showTournament(t.id)}catch(e){toast(e.message,true)}finally{b.disabled=false;b.textContent=original}
    }});
    box.scrollIntoView({behavior:"smooth",block:"start"});
  }catch(e){toast(e.message,true)}
}
function tournamentCard(t){const canJoin=t.status==="registration_open"||t.status==="open";const full=Number(t.registration_count||0)>=Number(t.max_players||0);const entrantLabel=Number(t.team_size||1)>1?"CLUBS":"PLAYERS";const button=canJoin&&!full?'<button class="qa qa-purple tournament-join" data-id="'+esc(t.id)+'">Join Tournament →</button>':'<a class="qa qa-blue" href="/tournaments#'+encodeURIComponent(t.id)+'">View Tournament →</a>';return '<article class="glass-panel tournament-card"><div class="tournament-card-art"><span>🏆</span><em>'+esc(statusLabel(t.status))+'</em></div><div class="tournament-card-body"><div class="tournament-card-top"><span>'+esc(t.format_label||t.format||"Tournament")+'</span><b>'+Number(t.registration_count||0)+'/'+Number(t.max_players||0)+' '+entrantLabel+'</b></div><h2>'+esc(t.name)+'</h2><p>'+esc(t.description||"ALU competition event.")+'</p><div class="tournament-meta"><span>📅 '+esc(t.start_time_label||"TBD")+'</span><span>🎯 '+esc(t.eligibility_label||"Open to players")+'</span></div><div class="tournament-card-actions">'+button+'</div></div></article>'}
async function load(){try{const me=await api("/api/me");window._me=me;const name=me.global_name||me.username||"Driver";if($("#user-name"))$("#user-name").textContent=name;if(me.staff)$("#staff-create").hidden=false;const guilds=await api("/api/guilds");window._adminGuild=(guilds.guilds||[]).find(x=>x.admin)||null;const data=await api("/api/tournaments");window._tournaments=data.tournaments||[];render()}catch(e){$("#tournament-list").innerHTML='<div class="tournament-empty">'+esc(e.message)+'</div>'}}
function render(){const filter=$("#tournament-filter").value;const all=window._tournaments||[];const rows=all.filter(t=>filter==="all"||t.status===filter||(filter==="open"&&t.status==="registration_open"));$("#tournament-count").textContent=rows.length+" tournament"+(rows.length===1?"":"s");$("#tournament-list").innerHTML=rows.length?rows.map(tournamentCard).join(""):'<div class="tournament-empty">No tournaments match this filter.</div>';document.querySelectorAll(".tournament-join").forEach(b=>b.addEventListener("click",()=>join(b.dataset.id)));document.querySelectorAll(".tournament-view").forEach(b=>b.addEventListener("click",()=>showTournament(b.dataset.id)))}
async function join(id){const b=document.querySelector('.tournament-join[data-id="'+CSS.escape(id)+'"]');if(b)b.disabled=true;try{const t=window._tournaments.find(x=>x.id===id);const payload={tournament_id:id};if(Number(t?.team_size||1)>1){const data=await api("/api/clubs");const clubs=(data.clubs||[]).filter(c=>c.leader);if(!clubs.length)throw new Error("You need to lead a club before entering this team tournament.");const choice=await chooseClub(clubs,t);if(!choice){if(b)b.disabled=false;return}payload.club_id=choice}const r=await api("/api/tournaments/register",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});toast(r.message||"Tournament registration submitted.");await load()}catch(e){toast(e.message,true);if(b)b.disabled=false}}
async function chooseClub(clubs,t){return new Promise(resolve=>{const wrap=document.createElement("div");wrap.className="club-picker-overlay";wrap.innerHTML='<div class="club-picker glass-panel"><span class="eyebrow">TEAM TOURNAMENT</span><h2>Choose Your Club</h2><p>'+esc(t.name)+' • '+Number(t.team_size||2)+'v'+Number(t.team_size||2)+'</p><select id="club-choice">'+clubs.map(c=>'<option value="'+esc(c.id)+'">'+esc(c.name)+' ('+Number(c.member_count||0)+'/20)</option>').join("")+'</select><div class="club-picker-actions"><button class="qa qa-blue" id="club-cancel">Cancel</button><button class="qa qa-purple" id="club-enter">Enter Tournament →</button></div></div>';document.body.appendChild(wrap);const close=v=>{wrap.remove();resolve(v)};wrap.querySelector("#club-cancel").onclick=()=>close(null);wrap.querySelector("#club-enter").onclick=()=>close(wrap.querySelector("#club-choice").value)})}
function syncEntrantCount(){const size=Number($("#create-tournament-form select[name=\"team_size\"]")?.value||1);const label=$("#entrant-count-label"),select=$("#entrant-count");if(!label||!select)return;const word=size>1?"Clubs":"Players";label.textContent=size>1?"Club Count":"Player Count";[...select.options].forEach(o=>o.textContent=o.value+" "+word)}
$("#create-tournament-form select[name=\"team_size\"]")?.addEventListener("change",syncEntrantCount);
$("#tournament-filter")?.addEventListener("change",render);
$("#create-tournament-form")?.addEventListener("submit",async e=>{e.preventDefault();const form=e.target;const submit=form.querySelector("button[type=\"submit\"]");const f=new FormData(form);const payload=Object.fromEntries(f.entries());payload.max_players=Number(payload.max_players||32);payload.gauntlet_only=f.get("gauntlet_only")==="on";const s=$("#create-status");if(s)s.textContent="Creating…";if(submit)submit.disabled=true;try{if(!window._adminGuild)throw new Error("No staff-enabled server is available.");await api("/api/tournaments?guild_id="+encodeURIComponent(window._adminGuild.id),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});form.reset();if(s)s.textContent="Tournament created.";await load()}catch(err){if(s)s.textContent=err.message}finally{if(submit)submit.disabled=false}});
function syncPrimaryNav(){const path=location.pathname;document.querySelectorAll(".top-nav nav a").forEach(a=>a.classList.remove("active"));const links=[...document.querySelectorAll(".top-nav nav a")];const a=links.find(x=>x.getAttribute("href")===path||((path==="/tournaments")&&x.getAttribute("href")==="/tournaments#clubs"));if(a)a.classList.add("active")}
document.addEventListener("DOMContentLoaded",()=>{syncPrimaryNav();load()});