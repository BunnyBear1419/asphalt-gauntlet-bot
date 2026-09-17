async function api(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (response.status === 401 || response.status === 403) { window.location.href = "/login"; return null; }
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}
function escapeHtml(value) { return String(value ?? "").replace(/[&<>\"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c])); }
let maps = [];
function render() {
  const term = document.getElementById("search").value.trim().toLowerCase();
  const filtered = maps.filter(m => m.track.toLowerCase().includes(term));
  document.getElementById("count").textContent = `${filtered.length} shown`;
  const rows = document.getElementById("rows");
  rows.innerHTML = filtered.map(m => `<tr><td><strong>${escapeHtml(m.track)}</strong></td><td>${escapeHtml(m.best_lap_time || "—")}</td><td>${escapeHtml(m.record_holder_id || "—")}</td><td>${escapeHtml(m.reference_lap_time || "No approved reference")}</td><td>${m.reference_video ? `<a href="${escapeHtml(m.reference_video)}" target="_blank" rel="noopener">View video</a>` : "—"}</td></tr>`).join("");
  document.getElementById("message").textContent = filtered.length ? "" : "No maps matched your search.";
  document.getElementById("table-wrap").hidden = !filtered.length;
}
async function init() {
  try {
    const data = await api("/api/maps");
    if (!data) return;
    maps = data.maps || [];
    render();
  } catch (error) { document.getElementById("message").textContent = `Unable to load Maps & Times: ${error.message}`; }
}
document.getElementById("search").addEventListener("input", render);
init();
