const $=s=>document.querySelector(s);
async function api(u,o={}){const r=await fetch(u,{credentials:"same-origin",...o});if(!r.ok)throw new Error(await r.text());return r.json()}
function setText(id,value){const el=document.getElementById(id);if(el)el.textContent=value}
async function load(){
  const g=await api("/api/guilds");
  const sel=$("#guild");
  if(!sel) return;
  sel.textContent="";
  g.guilds.forEach(x=>{const option=document.createElement("option");option.value=x.id;option.textContent=x.name;sel.append(option)});
  await profile();
}
async function profile(){
  const sel=$("#guild"); if(!sel||!sel.value)return;
  const id=encodeURIComponent(sel.value);
  try{
    const d=await api("/api/player/me?guild_id="+id),p=d.player||{},prefs=d.preferences||{};
    const elo=p.elo??"—";
    const pi=Number(p.garage_pi||0).toLocaleString();
    const season=p.season_number??"Not registered";
    const defense=p.defense_locked?"LOCKED":"OPEN";
    const wins=p.career_wins??0;
    const losses=Math.max(0,(p.career_played??0)-wins);
    const streak=p.streak??0;
    setText("elo",elo); setText("pi",pi); setText("profile-pi",pi);
    setText("right-elo",Number(elo||0).toLocaleString()); setText("right-pi",pi);
    setText("season",season); setText("season-number",p.season_number??"—"); setText("season-number-text",p.season_number??"—");
    setText("defense",defense); setText("wins",wins); setText("losses",losses); setText("streak",streak);
    setText("profile-name",p.username||"Driver"); setText("user-name",p.username||"Driver"); setText("welcome-name",p.username||"Driver");
    setText("season-status",p.season_number?"● Active ●":"● Not Registered ●");
    const tz=$("#timezone");
    if(tz && prefs.timezone)tz.value=prefs.timezone;
    const profile=$("#profile");
    if(profile){
      profile.textContent=p.game_id?`${p.game_id} • ${wins} career wins • ${p.career_played||0} matches`:"No registered driver profile yet.";
    }
  }catch(e){
    const profile=$("#profile"); if(profile)profile.textContent=e.message;
  }
}
const guild=$("#guild"); if(guild)guild.addEventListener("change",profile);
const save=$("#save");
if(save)save.addEventListener("click",async()=>{
  try{
    await api("/api/player/preferences?guild_id="+encodeURIComponent($("#guild").value),{
      method:"PUT",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({timezone:$("#timezone").value})
    });
    save.textContent="Saved ✓";
    setTimeout(()=>save.textContent="Save",1600);
  }catch(e){alert(e.message)}
});
const register=$("#register");
if(register)register.addEventListener("click",async()=>{
  const status=$("#registration-status");
  const payload={game_id:$("#registration-game-id")?.value||"",garage_pi:$("#registration-pi")?.value||"",control:$("#registration-control")?.value||"",proof_url:$("#registration-proof")?.value||""};
  if(status)status.textContent="Submitting registration…";
  register.disabled=true;
  try{
    const d=await api("/api/player/register?guild_id="+encodeURIComponent($("#guild").value),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    if(status)status.textContent=d.message||"Registration submitted for staff review.";
    await profile();
  }catch(e){if(status)status.textContent=e.message||"Registration failed."}
  finally{register.disabled=false}
});

async function loadDefense(){
  const sel=$("#guild"); if(!sel||!sel.value)return;
  const box=$("#defense-courses"), status=$("#defense-status"), msg=$("#defense-status-message");
  try{
    const d=await api("/api/player/defense?guild_id="+encodeURIComponent(sel.value));
    if(status)status.textContent=d.pending_review?"PENDING REVIEW":(d.locked.length?"ACTIVE":"READY");
    if(box){
      const courses=d.locked.length?d.locked:(d.pending.length?d.pending:d.tracks.map(track=>({track,car:"TBD",lap_time:"TBD"})));
      box.textContent="";
      courses.forEach((c,i)=>{
        const row=document.createElement("div");
        row.className="defense-course";
        const icon=document.createElement("i"); icon.textContent=String(i+1);
        const textEl=document.createElement("p");
        const b=document.createElement("b"); b.textContent=c.track||"Course";
        const small=document.createElement("small"); small.textContent=(c.car&&c.car!=="TBD"?c.car+" • ":"")+" "+(c.lap_time||"Results pending");
        textEl.append(b,small); row.append(icon,textEl); box.append(row);
      });
      if(!courses.length){const p=document.createElement("p");p.className="empty-state";p.textContent="No defense generated yet.";box.append(p)}
    }
    const submitCourses=d.pending.length?d.pending:d.tracks.map(track=>({track,car:"TBD",lap_time:"TBD"}));
    const defenseForm=$("#defense-submit-form");
    if(d.pending_review){if(defenseForm)defenseForm.hidden=true;}
    else if(!d.locked.length && submitCourses.length===5) renderDefenseForm(submitCourses,false);
    else if(d.pending_is_change && d.pending.length===5) renderDefenseForm(d.pending,true);
    const change=$("#defense-change");
    if(change)change.disabled=Boolean(d.cooldown_remaining||d.pending_review||!d.locked.length);
    const set=$("#defense-set");
    if(set)set.disabled=Boolean(d.pending_review||d.locked.length);
  }catch(e){if(msg)msg.textContent=e.message}
}

// Web defense results wizard.
function renderDefenseForm(courses, isChange=false){
  const form=$("#defense-submit-form"), fields=$("#defense-result-fields");
  if(!form||!fields)return;
  fields.textContent="";
  courses.forEach((course,i)=>{
    const wrap=document.createElement("fieldset"); wrap.className="defense-result-row";
    const legend=document.createElement("legend"); legend.textContent=`Course ${i+1}: ${course.track||"Course"}`;
    wrap.append(legend);
    const grid=document.createElement("div"); grid.className="defense-result-grid";
    const values=[
      ["lap_time","Lap time (MM:SS.MS)","text","Example: 1:23.456"],
      ["car","Car name","text","Exact car name"],
      ["car_rank","Car performance","number","Example: 2450"],
      ["proof_url","Proof image URL","url","Direct image URL"]
    ];
    values.forEach(([name,label,type,placeholder])=>{
      const labelEl=document.createElement("label"); labelEl.textContent=label;
      const input=document.createElement("input"); input.name=name; input.type=type; input.required=true; input.placeholder=placeholder;
      if(type==="number")input.min="1";
      labelEl.append(input); grid.append(labelEl);
    });
    wrap.append(grid); fields.append(wrap);
  });
  form.hidden=false; form.dataset.change=isChange?"1":"0";
}
async function submitDefense(e){
  e.preventDefault();
  const form=$("#defense-submit-form"), status=$("#defense-submit-status"), button=$("#defense-submit"), sel=$("#guild");
  if(!form||!sel?.value)return;
  const rows=[...document.querySelectorAll(".defense-result-row")];
  const courses=rows.map(row=>Object.fromEntries([...row.querySelectorAll("input")].map(x=>[x.name,x.value.trim()])));
  if(status)status.textContent="Submitting defense for staff review…";
  if(button)button.disabled=true;
  try{
    const d=await api("/api/player/defense?guild_id="+encodeURIComponent(sel.value),{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({action:"submit",courses,is_change:form.dataset.change==="1"})
    });
    if(status)status.textContent=d.message||"Defense submitted for staff review.";
    form.hidden=true; await loadDefense();
  }catch(err){if(status)status.textContent=err.message||"Defense submission failed."}
  finally{if(button)button.disabled=false}
}
const defenseForm=$("#defense-submit-form"); if(defenseForm)defenseForm.addEventListener("submit",submitDefense);

async function generateDefense(action){
  const sel=$("#guild"),msg=$("#defense-status-message"),button=action==="change"?$("#defense-change"):$("#defense-set");
  if(!sel||!sel.value)return;
  if(button)button.disabled=true;
  if(msg)msg.textContent="Generating five defense courses…";
  try{
    const d=await api("/api/player/defense?guild_id="+encodeURIComponent(sel.value),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(action==="change"?{action:"change"}:{action:"generate"})});
    if(msg)msg.textContent=d.message||"Defense courses generated.";
    await loadDefense();
  }catch(e){if(msg)msg.textContent=e.message||"Defense action failed."}
  finally{await loadDefense()}
}
const defenseSet=$("#defense-set"); if(defenseSet)defenseSet.addEventListener("click",()=>generateDefense("generate"));
const defenseChange=$("#defense-change"); if(defenseChange)defenseChange.addEventListener("click",()=>generateDefense("change"));
const originalLoad=load;
load=async()=>{await originalLoad();await loadDefense()};
if(guild)guild.addEventListener("change",loadDefense);

load().catch(e=>{const profile=$("#profile");if(profile)profile.textContent=e.message});
