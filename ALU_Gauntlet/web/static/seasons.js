async function api(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (response.status === 401 || response.status === 403) { window.location.href = "/login"; return null; }
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>\"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
}
function formatDate(value) {
  if (value == null || value === "") return "Not scheduled";
  const date = new Date(typeof value === "number" ? value * 1000 : value);
  return Number.isNaN(date.getTime()) ? "Unknown" : date.toLocaleString();
}
async function loadGuilds() {
  const data = await api("/api/guilds");
  if (!data) return false;
  const select = document.getElementById("guild");
  select.innerHTML = data.guilds.map(g => `<option value="${escapeHtml(g.id)}">${escapeHtml(g.name)}</option>`).join("");
  return data.guilds.length > 0;
}
async function loadSeasons() {
  const guild = document.getElementById("guild").value;
  const message = document.getElementById("message");
  if (!guild) { message.textContent = "No Discord server is available to this staff account."; return; }
  try {
    const data = await api(`/api/seasons?guild_id=${encodeURIComponent(guild)}`);
    if (!data) return;
    const current = data.current;
    document.getElementById("current-panel").hidden = false;
    document.getElementById("history-panel").hidden = false;
    document.getElementById("current-title").textContent = `Season ${current.season_number}`;
    document.getElementById("current-status").textContent = current.season_active ? "ACTIVE" : current.awaiting_staff_start ? "WAITING FOR STAFF START" : "DORMANT";
    document.getElementById("start").textContent = formatDate(current.starts_at);
    document.getElementById("end").textContent = formatDate(current.ends_at);
    document.getElementById("started").textContent = formatDate(current.started_at);
    document.getElementById("rollover").textContent = current.automatic_rollover ? "ON" : "OFF";
    document.getElementById("history-rows").innerHTML = data.history.length ? data.history.map(s => `<tr><td><strong>Season ${s.season_number}</strong></td><td>${s.player_count}</td><td>${escapeHtml(formatDate(s.closed_at))}</td><td><button class="button-link" type="button" data-season="${s.season_number}">View standings</button></td></tr>`).join("") : `<tr><td colspan="4">No completed season archives yet.</td></tr>`;
    message.textContent = "Season data loaded.";
    document.querySelectorAll("[data-season]").forEach(button => button.addEventListener("click", () => loadDetail(button.dataset.season)));
  } catch (error) { message.textContent = `Unable to load seasons: ${error.message}`; }
}
async function loadDetail(season) {
  const guild = document.getElementById("guild").value;
  try {
    const data = await api(`/api/seasons/${encodeURIComponent(season)}?guild_id=${encodeURIComponent(guild)}`);
    if (!data) return;
    const rows = data.season.standings || [];
    document.getElementById("detail-title").textContent = `Season ${data.season.season_number}`;
    document.getElementById("detail-rows").innerHTML = rows.length ? rows.map(r => `<tr><td>${escapeHtml(r.rank)}</td><td><code>${escapeHtml(r.user_id)}</code></td><td>${Number(r.elo).toLocaleString()}</td><td>${escapeHtml(r.division)}</td></tr>`).join("") : `<tr><td colspan="4">No standings were archived.</td></tr>`;
    document.getElementById("detail-panel").hidden = false;
    document.getElementById("detail-panel").scrollIntoView({behavior:"smooth", block:"start"});
  } catch (error) { document.getElementById("message").textContent = `Unable to load Season ${season}: ${error.message}`; }
}
document.getElementById("guild").addEventListener("change", loadSeasons);
document.getElementById("close-detail").addEventListener("click", () => { document.getElementById("detail-panel").hidden = true; });
(async function init() { try { if (await loadGuilds()) await loadSeasons(); else document.getElementById("message").textContent = "No Discord server is available to this staff account."; } catch (error) { document.getElementById("message").textContent = `Unable to load Seasons: ${error.message}`; } })();
