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
  const groups=[
    {title:"⚙️ Core Server Setup",description:"These settings control the main RSL Gauntlet experience.",fields:[
      ["admin_role_id","Gauntlet Admin Role","role"],["player_role_id","Gauntlet Driver Role","role"],
      ["registration_channel_id","Player Gauntlet Channel","channel"],["review_channel_id","Gauntlet Staff Channel","channel"],
      ["log_channel_id","Gauntlet Logs Channel","channel"],["announcement_channel_id","Gauntlet Announcement Channel","channel"],
      ["match_results_channel_id","Match Results Channel","channel"],["timezone","Server Timezone","timezone"]
    ]},
    {title:"🏆 Tournament Setup",description:"These settings control tournament registration, announcements, administration and match records.",fields:[
      ["tournament_player_announcement_role_id","Tournament Driver Role","role"],["tournament_admin_role_id","Tournament Admin Role","role"],
      ["tournament_main_channel_id","Player Tournament Channel","channel"],["tournament_log_channel_id","Tournament Logs Channel","channel"],
      ["tournament_bracket_channel_id","Tournament Bracket / Results Channel","channel"],["tournament_admin_channel_id","Tournament Admin Channel","channel"],
      ["tournament_announcement_channel_id","Tournament Announcement Channel","channel"]
    ]}
  ];
  let html="";
  for(const group of groups){
    html+="<div class='setup-group'><div class='setup-group-heading'><h3>"+group.title+"</h3><p>"+group.description+"</p></div><div class='setup-group-grid'>";
    for(const [key,label,type] of group.fields){
      let vals=[], selected=s[key]||"";
      if(type==="role") vals=options.roles; else if(type==="channel") vals=options.channels; else vals=options.timezones;
      html+="<label>"+esc(label)+"<select data-setting='"+esc(key)+"'><option value=''>Select…</option>"+
        vals.map(x=>"<option value='"+esc(x.id||x.value)+"' "+(selected===(x.id||x.value)?"selected":"")+">"+esc(x.name||x.label)+"</option>").join("")+
        "</select></label>";
    }
    html+="</div></div>";
  }
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
  const button=$("#save");
  if(!guild?.value||button?.disabled)return;
  const payload={};
  document.querySelectorAll("[data-setting]").forEach(x=>payload[x.dataset.setting]=x.value);
  const original=button?.textContent;
  if(button){button.disabled=true;button.textContent="Saving…"}
  $("#status").textContent="Saving server settings…";
  try{
    await api("/api/setup/settings?guild_id="+encodeURIComponent(guild.value),{
      method:"PUT",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify(payload)
    });
    $("#status").textContent="Saved ✓ — Discord will use these settings.";
    setTimeout(()=>$("#status").textContent="",3000)
  }catch(e){$("#status").textContent=e.message}
  finally{if(button){button.disabled=false;button.textContent=original}}
});

load().catch(e=>$("#status").textContent=e.message);

// Keep the shared top navigation state correct on every player page.
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
 else if(path==="/player") target=links.find(a=>a.getAttribute("href")==="/player" && !a.getAttribute("href").includes("#"));
 else if(path==="/") target=links.find(a=>a.getAttribute("href")==="/");
 if(target) target.classList.add("active");
}
document.addEventListener("DOMContentLoaded",syncPrimaryNav);
window.addEventListener("hashchange",syncPrimaryNav);
