(() => {
  const state={date:new Date(),filter:"all",events:[],reminders:[],lastSync:0,notifications:{gauntlet_notifications:false,tournament_notifications:false,subscribed_event_ids:[],muted_event_ids:[]}};
  const $=id=>document.getElementById(id);
  const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
  const dayKey=d=>{const y=d.getFullYear(),m=String(d.getMonth()+1).padStart(2,"0"),day=String(d.getDate()).padStart(2,"0");return y+"-"+m+"-"+day};
  const eventDate=e=>new Date((Number(e.start)||0)*1000);
  const filtered=()=>state.events.filter(e=>state.filter==="all"||e.type===state.filter||e.type==="personal");
  const notificationDays=e=>Number((state.notifications.event_lead_days||{})[String(e.id)] ?? state.notifications[e.type+"_lead_days"] ?? 1);
  const notificationEnabled=e=>{
    const subs=state.notifications.subscribed_event_ids||[], muted=state.notifications.muted_event_ids||[];
    return !muted.includes(String(e.id)) && (subs.includes(String(e.id)) || Boolean(state.notifications[e.type+"_notifications"]));
  };
  async function toggleEventNotification(e, leadDays){
    const id=String(e.id), enabled=!notificationEnabled(e);
    try{
      const r=await fetch("/api/notifications/event",{method:"PUT",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({event_id:id,enabled,lead_days:Number(leadDays)})});
      if(!r.ok)throw new Error(await r.text()||"Unable to save notification.");
      const d=await r.json();
      state.notifications.subscribed_event_ids=d.enabled
        ? [...new Set([...(state.notifications.subscribed_event_ids||[]),id])]
        : (state.notifications.subscribed_event_ids||[]).filter(x=>String(x)!==id);
      state.notifications.muted_event_ids=d.enabled
        ? (state.notifications.muted_event_ids||[]).filter(x=>String(x)!==id)
        : [...new Set([...(state.notifications.muted_event_ids||[]),id])];
      state.notifications.event_lead_days={...(state.notifications.event_lead_days||{}),[id]:Number(leadDays)};
      render();
      showEvent(e);
    }catch(err){alert(err.message||"Unable to save notification preference.");}
  }

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
    if(e.type==="personal"){showReminderForm(state.reminders.find(x=>String(x.id)===String(e.reminder_id)));return;}
    const old=document.querySelector(".calendar-modal");if(old)old.remove();
    const d=eventDate(e);
    const modal=document.createElement("div");modal.className="calendar-modal";modal.innerHTML=`<div class="calendar-modal-card" role="dialog" aria-modal="true" aria-label="Calendar event details"><button class="calendar-modal-close" type="button" aria-label="Close">×</button><span class="eyebrow">${esc(e.type==="gauntlet"?"GAUNTLET":"TOURNAMENT")}</span><h2>${esc(e.title)}</h2><p><strong>${esc(fmtDate(d))}</strong> at <strong>${esc(fmtTime(d))}</strong><br>${esc(e.guild_name||"RSL")} • ${esc(e.status||"scheduled")}</p><label class="calendar-notify-timing"><span>Remind me</span><select id="calendar-event-days"><option value="0">At event time</option><option value="1">1 day before</option><option value="2">2 days before</option><option value="3">3 days before</option><option value="7">1 week before</option><option value="14">2 weeks before</option><option value="30">30 days before</option><option value="custom">Custom…</option></select><input class="calendar-custom-days" id="calendar-event-custom-days" type="number" min="0" max="365" step="1" value="5" placeholder="Days"></label><button class="calendar-notify-button ${notificationEnabled(e)?"is-enabled":""}" type="button">${notificationEnabled(e)?"🔔 Notifications ON":"🔕 Notify me for this event"}</button></div>`;
    document.body.appendChild(modal);const close=()=>modal.remove();const timing=modal.querySelector("#calendar-event-days"),custom=modal.querySelector("#calendar-event-custom-days");
    const savedDays=notificationDays(e), presets=[0,1,2,3,7,14,30];
    if(timing)timing.value=presets.includes(savedDays)?String(savedDays):"custom";
    if(custom){custom.value=String(savedDays);custom.style.display=timing?.value==="custom"?"block":"none";}
    timing?.addEventListener("change",()=>{if(custom)custom.style.display=timing.value==="custom"?"block":"none";});modal.querySelector(".calendar-modal-close").onclick=close;modal.querySelector(".calendar-notify-button").onclick=()=>toggleEventNotification(e,timing?.value==="custom"?Math.max(0,Math.min(365,Number(custom?.value||0))):Number(timing?.value||0));modal.addEventListener("click",x=>{if(x.target===modal)close()});
  }
  function showReminderForm(existing=null){
    document.querySelector(".calendar-reminder-modal")?.remove();
    const modal=document.createElement("div");modal.className="calendar-modal calendar-reminder-modal";
    const localValue=existing?.local_time?String(existing.local_time).slice(0,16):"";
    modal.innerHTML='<div class="calendar-modal-card" role="dialog" aria-modal="true" aria-label="Personal reminder"><button class="calendar-modal-close" type="button" aria-label="Close">×</button><span class="eyebrow">PRIVATE CALENDAR</span><h2>'+(existing?"Edit Personal Reminder":"Create Personal Reminder")+'</h2><label>Title<input id="reminder-title" maxlength="120" placeholder="Practice night, car upgrade, meeting…" value="'+esc(existing?.title||"")+'"></label><label>Date &amp; time<input id="reminder-time" type="datetime-local" value="'+esc(localValue)+'"></label><label>Remind me<select id="reminder-lead"><option value="0">At event time</option><option value="1">1 day before</option><option value="2">2 days before</option><option value="3">3 days before</option><option value="7">1 week before</option><option value="14">2 weeks before</option><option value="30">30 days before</option><option value="custom">Custom…</option></select></label><input id="reminder-custom-lead" type="number" min="0" max="365" step="1" placeholder="Days before" style="display:none"><label>Note (optional)<textarea id="reminder-note" maxlength="500" placeholder="Anything you want included in the DM…">'+esc(existing?.note||"")+'</textarea><div class="calendar-reminder-actions"><button class="qa qa-purple" id="save-reminder" type="button">'+(existing?"Save Changes":"Create Reminder")+'</button>'+(existing?'<button class="qa qa-blue" id="delete-reminder" type="button">Delete</button>':"")+'</div><p id="reminder-status" class="form-status"></p></div>';
    document.body.appendChild(modal);
    const close=()=>modal.remove();modal.querySelector(".calendar-modal-close").onclick=close;modal.addEventListener("click",x=>{if(x.target===modal)close()});
    const lead=modal.querySelector("#reminder-lead"),custom=modal.querySelector("#reminder-custom-lead"),saved=Number(existing?.lead_days||0),presets=[0,1,2,3,7,14,30];
    if(lead){lead.value=presets.includes(saved)?String(saved):"custom";if(custom){custom.value=String(saved);custom.style.display=lead.value==="custom"?"block":"none"}lead.onchange=()=>{if(custom)custom.style.display=lead.value==="custom"?"block":"none"}}
    const getLead=()=>lead?.value==="custom"?Math.max(0,Math.min(365,Number(custom?.value||0))):Number(lead?.value||0);
    modal.querySelector("#save-reminder").onclick=async()=>{const status=modal.querySelector("#reminder-status"),button=modal.querySelector("#save-reminder"),title=modal.querySelector("#reminder-title").value.trim(),time=modal.querySelector("#reminder-time").value,note=modal.querySelector("#reminder-note").value.trim();if(!title||!time){status.textContent="Title and date/time are required.";return}button.disabled=true;status.textContent="Saving…";try{const url=existing?"/api/reminders/"+encodeURIComponent(existing.id):"/api/reminders";const rr=await fetch(url,{method:existing?"PUT":"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({title,remind_at:time,note,lead_days:getLead()})});if(!rr.ok)throw new Error(await rr.text()||"Unable to save reminder.");close();await load()}catch(err){status.textContent=err.message||"Unable to save reminder."}finally{button.disabled=false}};
    modal.querySelector("#delete-reminder")?.addEventListener("click",async()=>{if(!confirm("Delete this personal reminder?"))return;const status=modal.querySelector("#reminder-status");try{const rr=await fetch("/api/reminders/"+encodeURIComponent(existing.id),{method:"DELETE",credentials:"same-origin"});if(!rr.ok)throw new Error(await rr.text()||"Unable to delete reminder.");close();await load()}catch(err){status.textContent=err.message||"Unable to delete reminder."}});
  }
  function renderPersonalReminders(){const box=$("calendar-personal-list");if(!box)return;const rows=[...state.reminders].filter(x=>x.enabled!==false&&Number(x.timestamp)>0);if(!rows.length){box.innerHTML='<div class="calendar-empty">No personal reminders yet.</div>';return}box.innerHTML=rows.map(r=>{const d=new Date(Number(r.timestamp)*1000);return '<button type="button" class="calendar-agenda-item personal calendar-reminder-row" data-reminder-id="'+esc(r.id)+'"><strong>'+esc(r.title||"Personal Reminder")+'</strong><small>'+esc(fmtDate(d))+' • '+esc(fmtTime(d))+'</small><p>'+esc(r.timezone||"UTC")+' • '+esc(Number(r.lead_days||0)===0?"At event time":Number(r.lead_days)+" day(s) before")+'</p></button>'}).join("");box.querySelectorAll("[data-reminder-id]").forEach(b=>b.onclick=()=>showReminderForm(state.reminders.find(r=>String(r.id)===String(b.dataset.reminderId))))}
  $("calendar-add-reminder")?.addEventListener("click",()=>showReminderForm());
  async function load(){
    try{
      const r=await fetch("/api/calendar",{credentials:"same-origin",cache:"no-store"});
      if(!r.ok)throw new Error("Calendar request failed");
      const data=await r.json();state.events=Array.isArray(data.events)?data.events:[];
      try{const rr=await fetch("/api/reminders",{credentials:"same-origin",cache:"no-store"});if(rr.ok){const rd=await rr.json();state.reminders=Array.isArray(rd.reminders)?rd.reminders:[];const personal=state.reminders.filter(x=>x.enabled!==false&&Number(x.timestamp)>0).map(x=>({id:"personal-"+x.id,type:"personal",kind:"personal",title:x.title||"Personal Reminder",note:x.note||"",guild_name:"My Reminder",start:Number(x.timestamp),end:Number(x.timestamp),status:"personal",lead_days:Number(x.lead_days||0),timezone:x.timezone||"UTC",reminder_id:x.id}));state.events=[...state.events.filter(e=>e.type!=="personal"),...personal]}}catch(_){}
      try{const n=await fetch("/api/notifications",{credentials:"same-origin",cache:"no-store"});if(n.ok)state.notifications=await n.json()}catch(_){}state.lastSync=Date.now();
      $("calendar-sync").textContent="Live • updated "+new Date().toLocaleTimeString([], {hour:"numeric",minute:"2-digit"});
      render();renderPersonalReminders();
    }catch(e){$("calendar-sync").textContent="Sync unavailable";$("calendar-agenda-list").innerHTML='<div class="calendar-empty">Calendar data could not be loaded.</div>'}
  }
  $("calendar-prev").onclick=()=>{state.date.setMonth(state.date.getMonth()-1);render()};
  $("calendar-next").onclick=()=>{state.date.setMonth(state.date.getMonth()+1);render()};
  $("calendar-today").onclick=()=>{state.date=new Date();render()};
  document.querySelectorAll(".calendar-filter").forEach(b=>b.onclick=()=>{state.filter=b.dataset.filter;document.querySelectorAll(".calendar-filter").forEach(x=>x.classList.toggle("is-active",x===b));render()});
  renderPersonalReminders();load();setInterval(load,60000);
})();
