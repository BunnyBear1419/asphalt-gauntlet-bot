const labels = {
  registration_channel_id: "Main / registration channel",
  review_channel_id: "Staff review channel",
  log_channel_id: "Log channel",
  announcement_channel_id: "Announcement channel",
  match_results_channel_id: "Match-results channel",
  admin_role_id: "Staff / admin role",
  player_role_id: "Player role",
  timezone: "Server timezone",
};

function escapeHtml(value) {
  return String(value ?? "—").replace(/[&<>\"]/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[ch]));
}

async function loadGuilds() {
  const response = await fetch("/api/guilds", { cache: "no-store" });
  if (response.status === 401 || response.status === 403) { window.location.href = "/login"; return []; }
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return (await response.json()).guilds || [];
}

async function loadSetup(guildId) {
  const response = await fetch(`/api/setup?guild_id=${encodeURIComponent(guildId)}`, { cache: "no-store" });
  if (response.status === 401 || response.status === 403) { window.location.href = "/login"; return null; }
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return await response.json();
}

function render(data) {
  const grid = document.getElementById("setup-grid");
  const values = data.setup || {};
  grid.innerHTML = Object.entries(labels).map(([key, label]) => `<article class="card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(values[key])}</strong></article>`).join("");
  document.getElementById("setup-status").textContent = "Configuration is read-only from the web control center. Use the Discord picker-based setup wizard to change these values.";
}

async function init() {
  const select = document.getElementById("guild-select");
  try {
    const guilds = await loadGuilds();
    if (!guilds.length) { document.getElementById("setup-status").textContent = "No accessible Discord servers found."; return; }
    select.innerHTML = guilds.map(g => `<option value="${escapeHtml(g.id)}">${escapeHtml(g.name)}</option>`).join("");
    const refresh = async () => {
      document.getElementById("setup-status").textContent = "Loading configuration…";
      try { render(await loadSetup(select.value)); } catch (_) { document.getElementById("setup-status").textContent = "Unable to load server configuration."; }
    };
    select.addEventListener("change", refresh);
    await refresh();
  } catch (_) { document.getElementById("setup-status").textContent = "Unable to load accessible servers."; }
}
init();
