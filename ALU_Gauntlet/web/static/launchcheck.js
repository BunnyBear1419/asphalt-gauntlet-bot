function escapeHtml(value) {
  return String(value ?? "—").replace(/[&<>\"]/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[ch]));
}
async function api(path) {
  const response = await fetch(path, {cache:"no-store"});
  if (response.status === 401 || response.status === 403) { window.location.href="/login"; return null; }
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}
async function init() {
  const select=document.getElementById("guild-select"); const summary=document.getElementById("summary"); const meta=document.getElementById("meta"); const grid=document.getElementById("check-grid");
  try {
    const guildData=await api("/api/guilds"); if (!guildData) return;
    const guilds=guildData.guilds||[];
    if (!guilds.length) { summary.textContent="No server available"; meta.textContent="No accessible Discord servers were found."; return; }
    select.innerHTML=guilds.map(g=>`<option value="${escapeHtml(g.id)}">${escapeHtml(g.name)}</option>`).join("");
    async function refresh() {
      summary.textContent="Checking…"; meta.textContent="Running read-only checks…"; grid.innerHTML="";
      try {
        const data=await api(`/api/launchcheck?guild_id=${encodeURIComponent(select.value)}`); if (!data) return;
        summary.textContent=data.summary === "READY" ? "Ready" : "Not ready";
        meta.textContent=`${data.errors} error(s) • ${data.warnings} warning(s) • No automatic changes are made`;
        grid.innerHTML=(data.checks||[]).map(c=>`<article class="card"><span>${c.ok ? "✅" : (c.severity === "warning" ? "⚠️" : "❌")} ${escapeHtml(c.name)}</span><strong>${escapeHtml(c.detail)}</strong></article>`).join("");
      } catch (error) { summary.textContent="Check failed"; meta.textContent=`Unable to run launch check: ${error.message}`; }
    }
    select.addEventListener("change",refresh); await refresh();
  } catch (error) { summary.textContent="Unavailable"; meta.textContent=`Unable to load launch check: ${error.message}`; }
}
init();
