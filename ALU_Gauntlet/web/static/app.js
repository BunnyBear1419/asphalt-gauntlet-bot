const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;","\"":"&quot;"}[char]));
let selectedGuild = "";

async function api(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (response.status === 401 || response.status === 403) {
    window.location.href = "/login";
    throw new Error("Unauthorized");
  }
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function loadCurrentUser() {
  try {
    const user = await api("/api/me");
    $("user-name").textContent = user.global_name || user.username || "Staff";
    $("user-menu").hidden = false;
  } catch (_) {}
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? escapeHtml(value) : escapeHtml(date.toLocaleString());
}

function renderMatches(items) {
  if (!items.length) { $("recent-matches").innerHTML = '<div class="empty">No matches recorded yet.</div>'; return; }
  $("recent-matches").innerHTML = items.map((m) => `<div class="activity-row"><div><b>${escapeHtml(m.challenger_id)} vs ${escapeHtml(m.opponent_id)}</b><small>Season ${escapeHtml(m.season_number)} • ${formatDate(m.created_at)}</small></div><strong>${escapeHtml(m.courses_beat)}–${escapeHtml(5 - m.courses_beat)}</strong></div>`).join("");
}

function renderEvents(items) {
  if (!items.length) { $("recent-events").innerHTML = '<div class="empty">No recorded system events found.</div>'; return; }
  $("recent-events").innerHTML = items.map((e) => `<div class="activity-row"><div><b>${escapeHtml(e.action)}</b><small>${escapeHtml(e.type)} • ${formatDate(e.timestamp)}</small></div></div>`).join("");
}

async function loadGuilds() {
  const data = await api("/api/guilds");
  const select = $("guild-select");
  select.innerHTML = data.guilds.length ? data.guilds.map((g) => `<option value="${escapeHtml(g.id)}">${escapeHtml(g.name)}</option>`).join("") : '<option value="">No accessible servers</option>';
  if (!selectedGuild || !data.guilds.some((g) => g.id === selectedGuild)) selectedGuild = data.guilds[0]?.id || "";
  select.value = selectedGuild;
}

async function refreshOverview() {
  if (!selectedGuild) return;
  $("refresh-status").textContent = "Refreshing…";
  try {
    const [overview, status] = await Promise.all([api(`/api/analytics?guild_id=${encodeURIComponent(selectedGuild)}`), api(`/api/status`)]);
    const setup = await api(`/api/setup?guild_id=${encodeURIComponent(selectedGuild)}`);
    const seasons = await api(`/api/seasons?guild_id=${encodeURIComponent(selectedGuild)}`);
    const matches = await api(`/api/matches?guild_id=${encodeURIComponent(selectedGuild)}&limit=5`);
    const logs = await api(`/api/logs?guild_id=${encodeURIComponent(selectedGuild)}&limit=5`);
    const guilds = await api("/api/guilds");
    const guild = guilds.guilds.find((g) => g.id === selectedGuild);
    $("server-name").textContent = guild?.name || "Selected server";
    $("players").textContent = analyticsNumber(status, overview.players);
    $("registered").textContent = `${overview.registered ?? 0} registered this season`;
    $("defenses").textContent = overview.defenses ?? 0;
    $("pending").textContent = "Review from Defenses";
    $("matches").textContent = overview.matches ?? 0;
    $("completed").textContent = `${overview.completed_matches ?? 0} completed`;
    const current = seasons.current || {};
    $("season").textContent = `#${current.season_number ?? 1}`;
    $("season-state").textContent = current.season_active ? "Active" : current.awaiting_staff_start ? "Awaiting staff start" : "Inactive";
    const online = !!status.bot.online;
    $("system-pill").textContent = online ? "● Bot online" : "● Bot offline";
    const setupKeys = ["registration_channel_id","review_channel_id","log_channel_id","admin_role_id","player_role_id","timezone"];
    const missing = setupKeys.filter((key) => !setup.setup?.[key]);
    $("setup-status").textContent = missing.length ? `${missing.length} required setting${missing.length === 1 ? "" : "s"} missing` : "Complete";
    $("rollover-status").textContent = current.automatic_rollover ? "Enabled" : "Manual";
    $("health-card").innerHTML = `<b>${online ? "Bot connected" : "Bot offline"}</b><small>Latency: ${status.bot.latency_ms == null ? "—" : escapeHtml(status.bot.latency_ms + " ms")} • ${escapeHtml(status.bot.guild_count)} Discord server${status.bot.guild_count === 1 ? "" : "s"} connected</small>`;
    renderMatches(matches.matches || []);
    renderEvents(logs.logs || []);
    $("refresh-status").textContent = `Updated ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    if (error.message !== "Unauthorized") {
      $("refresh-status").textContent = "Unable to refresh overview";
      $("health-card").innerHTML = "<b>Overview unavailable</b><small>Check the bot connection, database and server access.</small>";
    }
  }
}

function analyticsNumber(status, fallback) { return fallback ?? "—"; }

$("guild-select").addEventListener("change", (event) => { selectedGuild = event.target.value; refreshOverview(); });

(async function init() {
  await loadCurrentUser();
  try { await loadGuilds(); await refreshOverview(); setInterval(refreshOverview, 15000); } catch (_) { $("refresh-status").textContent = "No accessible servers"; }
})();
