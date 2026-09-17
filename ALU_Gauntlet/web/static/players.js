async function api(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (response.status === 401 || response.status === 403) {
    window.location.href = "/login";
    return null;
  }
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>\"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"
  }[char]));
}

async function loadGuilds() {
  const data = await api("/api/guilds");
  if (!data) return false;
  const select = document.getElementById("guild-select");
  select.innerHTML = data.guilds.map((guild) => `<option value="${escapeHtml(guild.id)}">${escapeHtml(guild.name)}</option>`).join("");
  return data.guilds.length > 0;
}

async function loadPlayers() {
  const guild = document.getElementById("guild-select").value;
  const search = document.getElementById("player-search").value.trim();
  const state = document.getElementById("players-state");
  const wrap = document.getElementById("players-table-wrap");
  if (!guild) {
    state.textContent = "No Discord server is available to this staff account.";
    wrap.hidden = true;
    return;
  }
  try {
    const query = new URLSearchParams({ guild_id: guild });
    if (search) query.set("search", search);
    const data = await api(`/api/players?${query}`);
    if (!data) return;
    const body = document.getElementById("players-body");
    body.innerHTML = data.players.map((p) => `
      <tr>
        <td><strong>${escapeHtml(p.game_id || "—")}</strong><small>${escapeHtml(p.id)}</small></td>
        <td>${p.elo.toLocaleString()}</td>
        <td>${p.garage_pi.toLocaleString()}</td>
        <td>${p.season_registered ? `Season ${p.season_number}` : "Not registered"}</td>
        <td>${p.defense_locked ? "Locked" : "Not set"}</td>
        <td>${p.career_wins} wins / ${p.career_played} played</td>
      </tr>`).join("");
    document.getElementById("player-count").textContent = `${data.players.length} shown`;
    state.textContent = data.players.length ? "" : "No players matched this search.";
    wrap.hidden = data.players.length === 0;
  } catch (error) {
    state.textContent = `Unable to load players: ${error.message}`;
    wrap.hidden = true;
  }
}

async function init() {
  try {
    const available = await loadGuilds();
    if (available) await loadPlayers();
    else document.getElementById("players-state").textContent = "No Discord server is available to this staff account.";
  } catch (error) {
    document.getElementById("players-state").textContent = `Unable to load Players: ${error.message}`;
  }
}

document.getElementById("guild-select").addEventListener("change", loadPlayers);
let searchTimer;
document.getElementById("player-search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadPlayers, 250);
});
init();
