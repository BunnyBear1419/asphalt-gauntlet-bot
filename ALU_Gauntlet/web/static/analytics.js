async function api(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (response.status === 401 || response.status === 403) { window.location.href = "/login"; return null; }
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function loadGuilds() {
  const data = await api("/api/guilds");
  if (!data) return false;
  const select = document.getElementById("guild");
  select.innerHTML = data.guilds.map((g) => `<option value="${g.id}">${g.name}</option>`).join("");
  return data.guilds.length > 0;
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(typeof value === "number" ? value * 1000 : value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleDateString();
}

async function loadAnalytics() {
  const guild = document.getElementById("guild").value;
  const message = document.getElementById("message");
  if (!guild) { message.textContent = "No Discord server is available to this staff account."; return; }
  try {
    const data = await api(`/api/analytics?guild_id=${encodeURIComponent(guild)}`);
    if (!data) return;
    document.getElementById("players").textContent = data.players.toLocaleString();
    document.getElementById("registered").textContent = data.registered.toLocaleString();
    document.getElementById("defenses").textContent = data.defenses.toLocaleString();
    document.getElementById("matches").textContent = data.matches.toLocaleString();
    document.getElementById("completed").textContent = data.completed_matches.toLocaleString();
    document.getElementById("stats").hidden = false;
    const rows = document.getElementById("season-rows");
    rows.innerHTML = data.seasons.map((s) => `<tr><td><strong>Season ${s.season_number}</strong></td><td>${s.player_count.toLocaleString()}</td><td>${s.average_elo == null ? "—" : s.average_elo.toLocaleString()}</td><td>${formatDate(s.closed_at)}</td></tr>`).join("");
    document.getElementById("season-panel").hidden = data.seasons.length === 0;
    message.textContent = data.seasons.length ? "" : "No archived season data yet.";
  } catch (error) {
    document.getElementById("stats").hidden = true;
    document.getElementById("season-panel").hidden = true;
    message.textContent = `Unable to load Analytics: ${error.message}`;
  }
}

document.getElementById("guild").addEventListener("change", loadAnalytics);
(async () => {
  try {
    if (await loadGuilds()) await loadAnalytics();
    else document.getElementById("message").textContent = "No Discord server is available to this staff account.";
  } catch (error) { document.getElementById("message").textContent = `Unable to load Analytics: ${error.message}`; }
})();
