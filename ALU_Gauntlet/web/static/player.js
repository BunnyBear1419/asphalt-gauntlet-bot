const $=s=>document.querySelector(s);
async function api(u,o={}){const r=await fetch(u,{credentials:"same-origin",...o});if(!r.ok)throw new Error(await r.text());return r.json()}
function setText(id,value){const el=document.getElementById(id);if(el)el.textContent=value}
async function load(){
  const g=await api("/api/guilds");
  const sel=$("#guild");
  if(!sel) return;
  sel.innerHTML=g.guilds.map(x=>"<option value='"+x.id+"'>"+x.name+"</option>").join("");
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
load().catch(e=>{const profile=$("#profile");if(profile)profile.textContent=e.message});
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
