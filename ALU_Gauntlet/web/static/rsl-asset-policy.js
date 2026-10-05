(function(){
  const FALLBACKS={
    car:"/assets/rsl/visuals/rsl-car-silhouette.svg",
    track:"/assets/rsl/visuals/rsl-track-map.svg",
    division:"/assets/rsl/visuals/rsl-division-badge.svg"
  };
  const THEME_COLORS={
    "#28d7ff":"var(--rsl-box-accent)",
    "#2b7fff":"color-mix(in srgb,var(--rsl-box-accent) 78%,#000)",
    "#7b5cff":"color-mix(in srgb,var(--rsl-box-accent) 62%,#fff)",
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
    if(!src.includes("/assets/rsl/visuals/"))return;
    try{
      const response=await fetch(src,{cache:"force-cache"});
      if(!response.ok)throw new Error("asset fetch failed");
      const text=await response.text();
      const parser=new DOMParser();
      const doc=parser.parseFromString(themeSvg(text),"image/svg+xml");
      const svg=doc.documentElement;
      if(!svg||svg.tagName.toLowerCase()!=="svg")throw new Error("invalid SVG");
      svg.setAttribute("class",el.getAttribute("class")||"");
      svg.setAttribute("aria-hidden",el.getAttribute("aria-hidden")||"false");
      if(el.hasAttribute("alt"))svg.setAttribute("aria-label",el.getAttribute("alt"));
      svg.style.cssText=el.style.cssText;
      svg.dataset.rslThemed="true";
      svg.dataset.rslAssetType=el.dataset.rslAssetType||"";
      el.replaceWith(document.adoptNode(svg));
    }catch(_){
      /* Keep the source image if inline theming is unavailable. */
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
  function init(){document.querySelectorAll("img[data-rsl-asset-src]").forEach(apply)}
  window.RSLAssetPolicy={fallbacks:FALLBACKS,init};
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
})();
