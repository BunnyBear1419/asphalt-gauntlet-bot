(function(){
  const FALLBACKS={
    car:"/assets/rsl/visuals/rsl-car-silhouette.svg",
    track:"/assets/rsl/visuals/rsl-track-map.svg",
    division:"/assets/rsl/visuals/rsl-division-badge.svg"
  };
  function apply(el){
    if(!el)return;
    const src=el.dataset.rslAssetSrc;
    const fallback=el.dataset.rslFallback||FALLBACKS[el.dataset.rslAssetType]||FALLBACKS.car;
    if(!src){el.src=fallback;return}
    el.addEventListener("error",()=>{if(el.src!==new URL(fallback,location.href).href)el.src=fallback},{once:true});
    el.src=src;
  }
  function init(){document.querySelectorAll("img[data-rsl-asset-src]").forEach(apply)}
  window.RSLAssetPolicy={fallbacks:FALLBACKS,init};
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
})();
