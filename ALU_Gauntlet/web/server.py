  const hide=()=>{overlay.hidden=true;trigger.setAttribute("aria-expanded","false");};
  const show=()=>{overlay.hidden=false;trigger.setAttribute("aria-expanded","true");setTimeout(()=>input.focus(),20);};
  trigger.addEventListener("click",show); close.addEventListener("click",hide);
  overlay.addEventListener("click",e=>{if(e.target===overlay)hide();});
  document.addEventListener("keydown",e=>{if(e.key==="Escape")hide();if(e.key==="/"&&document.activeElement!==input){e.preventDefault();show();}});
  let timer; input.addEventListener("input",()=>{clearTimeout(timer);const q=input.value.trim();if(q.length<2){results.innerHTML="<p>Type at least 2 characters to search.</p>";return;}timer=setTimeout(async()=>{results.innerHTML="<p>Searching…</p>";try{const r=await fetch("/api/search?q="+encodeURIComponent(q),{credentials:"same-origin"});const d=await r.json();results.innerHTML=d.results.length?d.results.map(x=>'<a class="rsl-search-result" href="'+x.url+'"><strong>'+x.title+'</strong><span>'+x.snippet+'</span></a>').join(""):"<p>No matching pages found.</p>";}catch(_){results.innerHTML="<p>Search is temporarily unavailable.</p>";}},180);});
})();
</script>
'''

        footer_links = branding.get("links") or {}
        footer_identity = branding.get("identity") or {}
        footer_name = html.escape(str(footer_identity.get("name") or "Racing Syndicate League"))
        footer_tagline = html.escape(str(footer_identity.get("tagline") or "Race • Compete • Unite"))
        footer_logo_value = str(footer_identity.get("logo_url") or "/assets/rsl-shield.png")
        if footer_logo_value.rstrip("?").endswith("/assets/rsl-shield.png"):
            footer_logo_value = "/static/assets/rsl-footer-mark.png?v=20260921-rslfooter-png1"
        footer_logo = html.escape(footer_logo_value, quote=True)
        footer_social = {
            "x": str(footer_links.get("x") or "").strip(),
            "instagram": str(footer_links.get("instagram") or "").strip(),
            "youtube": str(footer_links.get("youtube") or "").strip(),
            "linkedin": "",
            "tiktok": "",
        }
        social_markup = ""
        custom_footer_items = []
        custom_links = footer_links.get("custom") if isinstance(footer_links.get("custom"), list) else []
        for index, item in enumerate(custom_links[:10], 1):
            if not isinstance(item, dict):
                continue
            href = str(item.get("url") or "").strip()
            name = str(item.get("name") or f"Link {index}").strip()[:80]
            icon = str(item.get("icon") or "").strip()
            if not href or item.get("enabled") is False:
                continue
            safe_href = html.escape(href, quote=True)
            safe_name = html.escape(name, quote=True)
            icon_markup = f'<img src="{html.escape(icon, quote=True)}" alt="" aria-hidden="true">' if icon else '<span aria-hidden="true">↗</span>'
            custom_footer_items.append(f'<a class="rsl-footer-social rsl-footer-custom-social" href="{safe_href}" target="_blank" rel="noopener noreferrer" aria-label="{safe_name}" title="{safe_name}">{icon_markup}</a>')
        custom_social_markup = "".join(custom_footer_items)
        if custom_social_markup:
            social_markup += custom_social_markup
        footer_markup = f'''
<footer class="rsl-footer" aria-label="{footer_name} footer">
  <div class="rsl-footer-social-row">
    <div class="rsl-footer-social-panel">
      <div class="rsl-footer-social-label">CONNECT WITH US</div>
      <div class="rsl-footer-socials">{social_markup}</div>
    </div>
  </div>
  <div class="rsl-footer-brand">
    <img src="{footer_logo}" alt="" aria-hidden="true">
    <div class="rsl-footer-brand-name">{footer_name}</div>
    <div class="rsl-footer-copyline">© 2026 {footer_name}™ <span aria-hidden="true">/</span> {footer_tagline}</div>
  </div>
  <nav class="rsl-footer-legal" aria-label="Legal and privacy">
    <a href="/legal">Legal Center</a><span aria-hidden="true">|</span>
    <a href="https://cash.app/" target="_blank" rel="noopener noreferrer">Creator Donation</a><span aria-hidden="true">|</span>
    <a href="/legal#privacy">Privacy Policy</a><span aria-hidden="true">|</span>
    <a href="/legal#security">Security</a><span aria-hidden="true">|</span>
    <a href="/legal#accessibility">Website Accessibility</a><span aria-hidden="true">|</span>
    <a href="/legal#cookies">Manage Cookies</a><span aria-hidden="true">|</span>
    <a href="/legal#privacy-choices"><span class="rsl-footer-privacy-icon" aria-hidden="true">✓×</span> Your Privacy Choices</a>
  </nav>
</footer>
'''
        # Put the same community entry/Help Center cards from Home on every other page.
        # Home already owns these cards, so skip index.html to avoid duplicates.
        if filename in {"legal.html"}:
            global_discord_markup = r'''