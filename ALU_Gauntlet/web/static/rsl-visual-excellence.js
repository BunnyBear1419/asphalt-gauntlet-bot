(function(){
  "use strict";
  const reduced=window.matchMedia&&window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  function init(){
    document.querySelectorAll(".rsl-visual-card,.home-feature-card,.home-upcoming-item,.glass-panel").forEach((el)=>{
      el.addEventListener("pointermove",(e)=>{
        if(reduced||window.innerWidth<900)return;
        const rect=el.getBoundingClientRect(),x=(e.clientX-rect.left)/rect.width-.5,y=(e.clientY-rect.top)/rect.height-.5;
        el.style.setProperty("--rsl-mx",(x*100).toFixed(1)+"%");
        el.style.setProperty("--rsl-my",(y*100).toFixed(1)+"%");
      });
      el.addEventListener("pointerleave",()=>{el.style.removeProperty("--rsl-mx");el.style.removeProperty("--rsl-my")});
    });
    document.querySelectorAll("[data-rsl-countup]").forEach((el)=>{
      const target=Number(el.dataset.rslCountup);
      if(!Number.isFinite(target)||reduced){el.textContent=String(target);return}
      const duration=900,start=performance.now(),from=Number(el.textContent.replace(/[^0-9.-]/g,""))||0;
      const tick=(now)=>{const p=Math.min(1,(now-start)/duration),e=1-Math.pow(1-p,3);el.textContent=Math.round(from+(target-from)*e).toLocaleString();if(p<1)requestAnimationFrame(tick)};
      requestAnimationFrame(tick);
    });
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init,{once:true});else init();
  window.RSLVisualExcellence={init};
})();