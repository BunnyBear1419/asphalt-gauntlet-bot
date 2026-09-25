(function(){
  const KEY="rsl_theme";
  const valid=t=>t==="light"||t==="dark";
  function apply(theme){
    const t=valid(theme)?theme:"dark";
    document.documentElement.setAttribute("data-theme",t);
    try{localStorage.setItem(KEY,t)}catch(e){}
    const select=document.querySelector("#profile-theme");
    if(select)select.value=t;
    try{window.dispatchEvent(new CustomEvent("rsl-theme-changed",{detail:{theme:t}}))}catch(e){}
    return t;
  }
  async function api(url,opts={}){
    const r=await fetch(url,{credentials:"same-origin",...opts});
    if(!r.ok)throw new Error(await r.text()||"Request failed");
    return r.json();
  }
  async function load(){
    try{const d=await api("/api/theme");apply(d.theme)}
    catch(e){\n      let cached="dark";\n      try{cached=localStorage.getItem(KEY)||cached}catch(_e){}\n      apply(document.documentElement.getAttribute("data-theme")||cached)\n    }
  }
  async function save(theme){
    const t=apply(theme);
    try{
      await api("/api/theme",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({theme:t})});
      const status=document.querySelector("#profile-save-status");
      if(status){status.textContent="Theme saved ✓";setTimeout(()=>{if(status.textContent==="Theme saved ✓")status.textContent=""},1800)}
    }catch(e){
      const status=document.querySelector("#profile-save-status");
      if(status)status.textContent="Theme could not be saved.";
    }
  }
  window.RSLTheme={apply,save,load};
  document.addEventListener("DOMContentLoaded",()=>{
    const select=document.querySelector("#profile-theme");
    if(select)select.addEventListener("change",()=>save(select.value));
    load();
  });
})();