const guildSelect = document.getElementById("guild");
const statusSelect = document.getElementById("status");
const searchInput = document.getElementById("search");
const rows = document.getElementById("rows");
const tableWrap = document.getElementById("table-wrap");
const message = document.getElementById("message");
let allDefenses = [];

async function loadGuilds() {
  const response = await fetch("/api/guilds", { cache: "no-store" });
  if (response.status === 401 || response.status === 403) return (window.location.href = "/login");
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();
  guildSelect.innerHTML = data.guilds.length
    ? data.guilds.map(g => `<option value="${g.id}">${escapeHtml(g.name)}</option>`).join("")
    : `<option value="">No accessible servers</option>`;
  if (data.guilds.length) await loadDefenses();
}

async function loadDefenses() {
  if (!guildSelect.value) return;
  message.textContent = "Loading defenses…";
  tableWrap.hidden = true;
  const params = new URLSearchParams({ guild_id: guildSelect.value, status: statusSelect.value });
  const response = await fetch(`/api/defenses?${params}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  allDefenses = (await response.json()).defenses || [];
  render();
}

function render() {
  const term = searchInput.value.trim().toLowerCase();
  const filtered = allDefenses.filter(d => !term || String(d.game_id || "").toLowerCase().includes(term) || String(d.id || "").includes(term));
  rows.innerHTML = filtered.map(d => {
    const courseCount = d.locked_courses.length;
    const review = d.review_pending ? (d.review_is_change ? "Change pending" : "New defense pending") : "—";
    const status = d.review_pending ? "Pending review" : d.locked ? "Locked" : "Not set";
    return `<tr><td><strong>${escapeHtml(d.game_id || "Unregistered game ID")}</strong><small>${escapeHtml(d.id || "Unknown Discord ID")}</small></td><td>${status}</td><td>${courseCount}/5 locked${d.review_pending ? ` • ${d.review_courses.length}/5 submitted` : ""}</td><td>${review}</td></tr>`;
  }).join("");
  message.textContent = filtered.length ? `${filtered.length} defense record${filtered.length === 1 ? "" : "s"}.` : "No defense records match this filter.";
  tableWrap.hidden = !filtered.length;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;","\"":"&quot;"}[c]));
}

guildSelect.addEventListener("change", loadDefenses);
statusSelect.addEventListener("change", loadDefenses);
searchInput.addEventListener("input", render);
loadGuilds().catch(error => { message.textContent = `Unable to load defenses: ${error.message}`; });
