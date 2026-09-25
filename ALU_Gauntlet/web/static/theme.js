(function(){
  const KEY="rsl_theme";
  const THEMES=["dark","light","ocean","purple","crimson","emerald","sunset","graphite"];
  const valid=t=>THEMES.includes(t);
  const selectors="#profile-theme,#rsl-profile-theme-select,#rsl-footer-theme-select";

  function syncControls(theme){
    document.querySelectorAll(selectors).forEach(select=>{
      if(select.value!==theme) select.value=theme;
    });
  }

  function apply(theme){
    const t=valid(theme)?theme:"dark";
    document.documentElement.setAttribute("data-theme",t);
    try{localStorage.setItem(KEY,t)}catch(e){}
    syncControls(t);
    try{window.dispatchEvent(new CustomEvent("rsl-theme-changed",{detail:{theme:t}}))}catch(e){}
    return t;
  }

  async function api(url,opts={}){
    const r=await fetch(url,{credentials:"same-origin",cache:"no-store",...opts});
    if(!r.ok)throw new Error(await r.text()||"Request failed");
    return r.json();
  }

  async function load(){
    let cached="";
    try{cached=localStorage.getItem(KEY)||""}catch(_e){}
    if(valid(cached)) apply(cached);
    try{
      const d=await api("/api/theme");
      if(d && d.saved===true && valid(d.theme)) apply(d.theme);
      else if(!valid(cached)) apply("dark");
    }catch(e){
      if(valid(cached)) apply(cached);
      else apply(document.documentElement.getAttribute("data-theme")||"dark");
    }
  }

  async function save(theme){
    const t=apply(theme);
    try{
      await api("/api/theme",{
        method:"PUT",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({theme:t})
      });
      const status=document.querySelector("#profile-save-status");
      if(status){
        status.textContent="Theme saved ✓";
        setTimeout(()=>{if(status.textContent==="Theme saved ✓")status.textContent=""},1800);
      }
      return true;
    }catch(e){
      console.error("RSL theme save failed:",e);
      const status=document.querySelector("#profile-save-status");
      if(status)status.textContent="Theme could not be saved.";
      return false;
    }
  }

  window.RSLTheme={apply,save,load,THEMES};

  document.addEventListener("change",e=>{
    const select=e.target.closest?.(selectors);
    if(select) save(select.value);
  });

  const syncAll=()=>syncControls(document.documentElement.getAttribute("data-theme")||"dark");

  document.addEventListener("DOMContentLoaded",()=>{
    load();
    syncAll();
    window.addEventListener("rsl-theme-changed",syncAll);
    const observer=new MutationObserver(syncAll);
    observer.observe(document.body,{childList:true,subtree:true});
  });
})();