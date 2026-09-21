(() => {
  const state={date:new Date(),filter:"all",events:[],lastSync:0};
  const $=id=>document.getElementById(id);
  const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
  const dayKey=d=>{const y=d.getFullYear(),m=String(d.getMonth()+1).padStart(2,"0"),day=String(d.getDate()).padStart(2,"0");return y+"-"+m+"-"+day};
  const eventDate=e=>new Date((Number(e.start)||0)*1000);
  const filtered=()=>state.events.filter(e=>state.filter==="all"||e.type===state.filter);
  const fmtTime=d=>d.toLocaleTimeString([], {hour:"numeric",minute:"2-digit"});
  const fmtDate=d=>d.toLocaleDateString([], {month:"short",day:"numeric",year:"numeric"});
  const monthLabel=()=>state.date.toLocaleDateString([], {month:"long",year:"numeric"});
  function render(){
    $("calendar-month").textContent=monthLabel();
    const year=state.date.getFullYear(), month=state.date.getMonth();
    const first=new Date(year,month,1), start=new Date(year,month,1-first.getDay());
    const events=filtered(), byDay={};
    events.forEach(e=>{const d=eventDate(e);if(!Number.isNaN(d.getTime()))(byDay[dayKey(d)]??=[]).push(e)});
    let html="";
    for(let i=0;i<42;i++){
      const d=new Date(start);d.setDate(start.getDate()+i);
      const key=dayKey(d), outside=d.getMonth()!==month, today=key===dayKey(new Date());
      const list=(byDay[key]||[]).sort((a,b)=>(a.start-b.start));
      html+=`<div class="calendar-cell ${outside?"is-outside":""} ${today?"is-today":""}" role="gridcell" aria-label="${esc(d.toLocaleDateString([], {dateStyle:"full"}))}">
        <div class="calendar-date">${d.getDate()}</div><div class="calendar-events">`;
      list.slice(0,3).forEach(e=>{
        const cls=e.kind==="registration"?"registration":e.type;
        html+=`<button class="calendar-event ${cls}" type="button" data-event-id="${esc(e.id)}"><span>${esc(e.title)}</span><span class="calendar-event-time">${fmtTime(eventDate(e))}</span></button>`;
      });
      if(list.length>3) html+=`<div class="calendar-more">+${list.length-3} more</div>`;
      html+="</div></div>";
    }
    $("calendar-grid").innerHTML=html;
    $("calendar-grid").querySelectorAll(".calendar-event").forEach(b=>b.addEventListener("click",()=>showEvent(state.events.find(e=>e.id===b.dataset.eventId))));
    const upcoming=events.filter(e=>eventDate(e)>=new Date()).sort((a,b)=>a.start-b.start).slice(0,12);
    $("event-count").textContent=events.length+" event"+(events.length===1?"":"s");
    $("calendar-agenda-list").innerHTML=upcoming.length?upcoming.map(e=>{
      const cls=e.kind==="registration"?"registration":e.type;
      return `<article class="calendar-agenda-item ${cls}"><strong>${esc(e.title)}</strong><small>${esc(fmtDate(eventDate(e)))} • ${esc(fmtTime(eventDate(e)))}</small><p>${esc(e.guild_name||"RSL")} • ${esc(e.status||"scheduled")}</p></article>`;
    }).join(""):'<div class="calendar-empty">No upcoming events.</div>';
  }
  function showEvent(e){
    if(!e)return;
    const old=document.querySelector(".calendar-modal");if(old)old.remove();
    const d=eventDate(e);
    const modal=document.createElement("div");modal.className="calendar-modal";modal.innerHTML=`<div class="calendar-modal-card" role="dialog" aria-modal="true" aria-label="Calendar event details"><button class="calendar-modal-close" type="button" aria-label="Close">×</button><span class="eyebrow">${esc(e.type==="gauntlet"?"GAUNTLET":"TOURNAMENT")}</span><h2>${esc(e.title)}</h2><p><strong>${esc(fmtDate(d))}</strong> at <strong>${esc(fmtTime(d))}</strong><br>${esc(e.guild_name||"RSL")} • ${esc(e.status||"scheduled")}</p></div>`;
    document.body.appendChild(modal);const close=()=>modal.remove();modal.querySelector(".calendar-modal-close").onclick=close;modal.addEventListener("click",x=>{if(x.target===modal)close()});
  }
  async function load(){
    try{
      const r=await fetch("/api/calendar",{credentials:"same-origin",cache:"no-store"});
      if(!r.ok)throw new Error("Calendar request failed");
      const data=await r.json();state.events=Array.isArray(data.events)?data.events:[];state.lastSync=Date.now();
      $("calendar-sync").textContent="Live • updated "+new Date().toLocaleTimeString([], {hour:"numeric",minute:"2-digit"});
      render();
    }catch(e){$("calendar-sync").textContent="Sync unavailable";$("calendar-agenda-list").innerHTML='<div class="calendar-empty">Calendar data could not be loaded.</div>'}
  }
  $("calendar-prev").onclick=()=>{state.date.setMonth(state.date.getMonth()-1);render()};
  $("calendar-next").onclick=()=>{state.date.setMonth(state.date.getMonth()+1);render()};
  $("calendar-today").onclick=()=>{state.date=new Date();render()};
  document.querySelectorAll(".calendar-filter").forEach(b=>b.onclick=()=>{state.filter=b.dataset.filter;document.querySelectorAll(".calendar-filter").forEach(x=>x.classList.toggle("is-active",x===b));render()});
  load();setInterval(load,60000);
})();
