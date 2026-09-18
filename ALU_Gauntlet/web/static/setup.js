const $=s=>document.querySelector(s);
let options={channels:[],roles:[],timezones:[]};

async function api(u,o={}){const r=await fetch(u,{credentials:"same-origin",...o});if(!r.ok)throw new Error(await r.text());return r.json()}
function esc(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}

async function loadOptions(){
  const guild=$("#guild");
  if(!guild?.value){
    options={channels:[],roles:[],timezones:[]};
    $("#fields").innerHTML="<p class='empty-state'>No staff-managed Discord server is available.</p>";
    return;
  }
  options=await api("/api/setup/options?guild_id="+encodeURIComponent(guild.value));
}

async function load(){
  const g=await api("/api/guilds");
  const guilds=(g.guilds||[]).filter(x=>x.admin);
  const guild=$("#guild");
  guild.innerHTML=guilds.map(x=>"<option value='"+esc(x.id)+"'>"+esc(x.name)+"</option>").join("");
  if(!guilds.length){
    $("#fields").innerHTML="<p class='empty-state'>No Discord servers are available for staff setup.</p>";
    $("#save").disabled=true;
    return;
  }
  await loadOptions();
  await render();
}

async function render(){
  const guild=$("#guild");
  if(!guild?.value)return;
  const s=(await api("/api/setup/settings?guild_id="+encodeURIComponent(guild.value))).settings;
  let html="";
  for(const [key,label] of [
    ["registration_channel_id","Main / registration channel"],
    ["review_channel_id","Staff review channel"],
    ["log_channel_id","Log channel"],
    ["announcement_channel_id","Announcement channel"],
    ["match_results_channel_id","Match-results channel"],
    ["admin_role_id","Staff / admin role"],
    ["player_role_id","Player role"]
  ]){
    const vals=key.endsWith("_role_id")?options.roles:options.channels;
    html+="<label>"+label+"<select data-setting='"+key+"'><option value=''>Select…</option>"+
      vals.map(x=>"<option value='"+esc(x.id)+"' "+(s[key]===x.id?"selected":"")+">"+esc(x.name)+"</option>").join("")+
      "</select></label>";
  }
  html+="<label>Timezone<select data-setting='timezone'>"+
    options.timezones.map(x=>"<option value='"+esc(x.value)+"' "+(s.timezone===x.value?"selected":"")+">"+esc(x.label)+"</option>").join("")+
    "</select></label>";
  $("#fields").innerHTML=html;
}

$("#guild").addEventListener("change",async()=>{
  $("#status").textContent="Loading server options…";
  try{
    await loadOptions();
    await render();
    $("#status").textContent="";
  }catch(e){
    $("#status").textContent=e.message;
  }
});

$("#save").addEventListener("click",async()=>{
  const guild=$("#guild");
  if(!guild?.value)return;
  const payload={};
  document.querySelectorAll("[data-setting]").forEach(x=>payload[x.dataset.setting]=x.value);
  try{
    await api("/api/setup/settings?guild_id="+encodeURIComponent(guild.value),{
      method:"PUT",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify(payload)
    });
    $("#status").textContent="Saved ✓ — Discord will use these settings.";
    setTimeout(()=>$("#status").textContent="",3000)
  }catch(e){$("#status").textContent=e.message}
});

load().catch(e=>$("#status").textContent=e.message);