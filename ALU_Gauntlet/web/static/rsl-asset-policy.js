(function(){
  const FALLBACKS={
    car:"/static/assets/rsl/visuals/rsl-car-silhouette.svg",
    track:"/static/assets/rsl/visuals/rsl-track-map.svg",
    division:"/static/assets/rsl/visuals/rsl-division-badge.svg"
  };
  const THEME_COLORS={
    "#28d7ff":"var(--rsl-box-accent)",
    "#2b7fff":"var(--rsl-box-accent)",
    "#7b5cff":"var(--rsl-box-accent)",
    "#071321":"var(--rsl-box)",
    "#0a1a2d":"var(--rsl-box-alt)",
    "#0f2a43":"var(--rsl-box-line)",
    "#91a9c4":"var(--rsl-box-muted)",
    "#050b14":"var(--rsl-box)",
    "#fff":"var(--rsl-box-text)"
  };
  function themeSvg(svg){
    Object.entries(THEME_COLORS).forEach(([from,to])=>{
      svg=svg.split(from).join(to);
      svg=svg.split(from.toUpperCase()).join(to);
    });
    return svg;
  }
  async function themeOriginal(el,src){
    if(!src.includes("/static/assets/rsl/visuals/"))return;
    try{
      const response=await fetch(src,{cache:"no-store"});
      if(!response.ok)throw new Error("asset fetch failed");
      let markup=themeSvg(await response.text());
      const cls=el.getAttribute("class")||"";
      const aria=el.getAttribute("aria-label")||el.getAttribute("alt")||"";
      markup=markup.replace(
        "<svg ",
        '<svg class="'+cls.replace(/"/g,"&quot;")+'" data-rsl-themed="true" aria-label="'+aria.replace(/"/g,"&quot;")+'" '
      );
      const template=document.createElement("template");
      template.innerHTML=markup.trim();
      const svg=template.content.firstElementChild;
      if(!svg||svg.tagName.toLowerCase()!=="svg")throw new Error("invalid SVG");
      if(el.style.cssText)svg.style.cssText=el.style.cssText;
      svg.dataset.rslAssetType=el.dataset.rslAssetType||"";
      el.replaceWith(svg);
    }catch(_){
      /* Keep the original image if inline theming is unavailable. */
    }
  }
  function apply(el){
    if(!el)return;
    const src=el.dataset.rslAssetSrc;
    const fallback=el.dataset.rslFallback||FALLBACKS[el.dataset.rslAssetType]||FALLBACKS.car;
    if(!src){el.src=fallback;return}
    el.addEventListener("error",()=>{if(el.src!==new URL(fallback,location.href).href)el.src=fallback},{once:true});
    el.src=src;
    themeOriginal(el,src);
  }
  function init(){document.querySelectorAll("img[data-rsl-asset-src]:not([data-rsl-themed])").forEach(apply)}
  window.RSLAssetPolicy={fallbacks:FALLBACKS,init};
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
})();
