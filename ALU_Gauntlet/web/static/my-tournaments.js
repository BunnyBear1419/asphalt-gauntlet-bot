(() => {
const $=s=>document.querySelector(s);
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmtDate=v=>{if(!v)return "Date TBD";try{return new Date(v).toLocaleString([],{month:"short",day:"numeric",year:"numeric",hour:"numeric",minute:"2-digit"})}catch(_){return "Date TBD"}};
const statusLabel=s=>({registration_open:"Registration Open",open:"Registration Open",live:"Live",completed:"Completed"}[s]||String(s||"Unknown").replaceAll("_"," "));
const card=t=>{
 const team=t.team_size>1?(t.team_size+"v"+t.team_size):"Solo";
 const progress=t.status==="completed"?(t.finish||"Completed"):(t.current_round?("Round "+t.current_round+" • "+(t.matches_played||0)+" matches played"):"Registered • Awaiting tournament progress");
 const reg=t.registration_status?String(t.registration_status).replaceAll("_"," "):"Registered";
 return '<article class="my-tournament-card"><div><h3>'+esc(t.name)+'</h3><div class="my-tournament-meta"><span class="my-tournament-tag my-tournament-status">'+esc(statusLabel(t.status))+'</span><span class="my-tournament-tag">'+esc(team)+'</span><span class="my-tournament-tag">'+esc(t.format_label)+'</span><span class="my-tournament-tag">'+esc(fmtDate(t.start_time))+'</span><span class="my-tournament-tag">Registration: '+esc(reg)+'</span></div><div class="my-tournament-progress">'+esc(progress)+' • '+(t.wins||0)+'W / '+(t.losses||0)+'L</div></div><div class="my-tournament-actions"><a class="my-tournament-button" href="/tournaments?open='+encodeURIComponent(t.id)+'">Tournament Center →</a><a class="my-tournament-button secondary" href="/tournaments/matches">Matches →</a></div></article>';
};
async function load(){
 try{
  const r=await fetch("/api/profile/tournaments",{credentials:"same-origin"});if(!r.ok)throw new Error("Unable to load tournament history.");
  const d=await r.json(),all=d.tournaments||[],upcoming=d.upcoming||[],history=d.history||[],st=d.stats||{};
  $("#stat-entered").textContent=st.entered??all.length;$("#stat-upcoming").textContent=upcoming.length;$("#stat-completed").textContent=st.completed??history.length;$("#stat-wins").textContent=st.wins??0;$("#stat-rate").textContent=(st.win_rate??0)+"%";
  $("#upcoming-list").innerHTML=upcoming.length?upcoming.map(card).join(""):'<div class="my-tournament-empty">You have no active or upcoming tournament registrations.</div>';
  $("#history-list").innerHTML=history.length?history.map(card).join(""):'<div class="my-tournament-empty">Your completed tournament history will appear here.</div>';
 }catch(e){$("#upcoming-list").innerHTML='<div class="my-tournament-empty">'+esc(e.message||"Unable to load your tournaments.")+'</div>';$("#history-list").innerHTML="";}
}
load();
})();