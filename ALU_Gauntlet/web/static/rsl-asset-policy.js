(function(){
  const FALLBACKS={
    car:"/static/assets/rsl/visuals/rsl-car-silhouette.svg",
    track:"/static/assets/rsl/visuals/rsl-track-map.svg",
    division:"/static/assets/rsl/visuals/rsl-division-badge.svg"
  };
  const COLOR_KEYS={
    accent:["#28d7ff","#2b7fff","#7b5cff"],
    surface:["#071321","#050b14"],
    surfaceAlt:["#0a1a2d"],
    line:["#0f2a43"],
    muted:["#91a9c4"],
    text:["#fff"]
  };
  const cache=new Map();

  function themeValues(){
    const root=getComputedStyle(document.documentElement);
    return {
      accent:(root.getPropertyValue("--rsl-box-accent")||"#25dfff").trim(),
      surface:(root.getPropertyValue("--rsl-box")||"#071427").trim(),
      surfaceAlt:(root.getPropertyValue("--rsl-box-alt")||"#0b1d34").trim(),
      line:(root.getPropertyValue("--rsl-box-line")||"#173b64").trim(),
      muted:(root.getPropertyValue("--rsl-box-muted")||"#91a5c3").trim(),
      text:(root.getPropertyValue("--rsl-box-text")||"#dbe8f8").trim()
    };
  }

  function themeSvg(markup){
    const c=themeValues();
    const replacements=[
      [COLOR_KEYS.accent,c.accent],
      [COLOR_KEYS.surface,c.surface],
      [COLOR_KEYS.surfaceAlt,c.surfaceAlt],
      [COLOR_KEYS.line,c.line],
      [COLOR_KEYS.muted,c.muted],
      [COLOR_KEYS.text,c.text]
    ];
    replacements.forEach(([keys,to])=>keys.forEach(from=>{
      markup=markup.split(from).join(to);
      markup=markup.split(from.toUpperCase()).join(to);
    }));
    return markup;
  }

  async function getMarkup(src){
    if(!cache.has(src)){
      cache.set(src,fetch(src,{cache:"no-store"}).then(async response=>{
        if(!response.ok)throw new Error("asset fetch failed");
        return response.text();
      }));
    }
    return cache.get(src);
  }

  async function themeOriginal(el,src){
    if(!src||!src.includes("/static/assets/rsl/visuals/"))return;
    try{
      let markup=themeSvg(await getMarkup(src));
      const cls=el.getAttribute("class")||"";
      const aria=el.getAttribute("aria-label")||el.getAttribute("alt")||"";
      markup=markup.replace(
        "<svg ",
        '<svg class="'+cls.replace(/"/g,"&quot;")+'" data-rsl-themed="true" data-rsl-asset-src="'+src.replace(/"/g,"&quot;")+'" data-rsl-asset-type="'+(el.dataset.rslAssetType||"")+'" aria-label="'+aria.replace(/"/g,"&quot;")+'" '
      );
      const template=document.createElement("template");
      template.innerHTML=markup.trim();
      const svg=template.content.firstElementChild;
      if(!svg||svg.tagName.toLowerCase()!=="svg")throw new Error("invalid SVG");
      if(el.style.cssText)svg.style.cssText=el.style.cssText;
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

  function retheme(){
    document.querySelectorAll("svg[data-rsl-themed][data-rsl-asset-src]").forEach(svg=>{
      const src=svg.dataset.rslAssetSrc;
      const replacement=document.createElement("img");
      replacement.src=src;
      replacement.className=svg.getAttribute("class")||"";
      replacement.alt=svg.getAttribute("aria-label")||"";
      replacement.dataset.rslAssetSrc=src;
      replacement.dataset.rslAssetType=svg.dataset.rslAssetType||"";
      if(svg.style.cssText)replacement.style.cssText=svg.style.cssText;
      svg.replaceWith(replacement);
      themeOriginal(replacement,src);
    });
  }

  function init(){
    document.querySelectorAll("img[data-rsl-asset-src]:not([data-rsl-themed])").forEach(apply);
    if(!window.__rslThemeAssetObserver){
      window.__rslThemeAssetObserver=new MutationObserver(mutations=>{
        if(mutations.some(m=>m.type==="attributes"&&m.attributeName==="data-theme"))retheme();
      });
      window.__rslThemeAssetObserver.observe(document.documentElement,{attributes:true});
    }
  }

  window.RSLAssetPolicy={fallbacks:FALLBACKS,init,retheme};
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",init);else init();
})();