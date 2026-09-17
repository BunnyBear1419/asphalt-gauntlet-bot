async function loadCurrentUser() {
  const menu = document.getElementById("user-menu");
  const name = document.getElementById("user-name");
  try {
    const response = await fetch("/api/me", { cache: "no-store" });
    if (!response.ok) return;
    const user = await response.json();
    name.textContent = user.global_name || user.username || "Staff";
    menu.hidden = false;
  } catch (_) {
    // The server remains the source of truth for authorization.
  }
}

async function refreshStatus() {
  const pill = document.getElementById("system-pill");
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (response.status === 401 || response.status === 403) {
      window.location.href = "/login";
      return;
    }
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const online = data.bot.online;
    document.getElementById("bot-status").textContent = online ? "Online" : "Offline";
    document.getElementById("latency").textContent = data.bot.latency_ms == null ? "—" : `${data.bot.latency_ms} ms`;
    document.getElementById("guilds").textContent = data.bot.guild_count;
    pill.textContent = online ? "● Bot online" : "● Bot offline";
  } catch (_) {
    document.getElementById("bot-status").textContent = "Unavailable";
    document.getElementById("latency").textContent = "—";
    document.getElementById("guilds").textContent = "—";
    pill.textContent = "● Control center unavailable";
  }
}

loadCurrentUser();
refreshStatus();
setInterval(refreshStatus, 10000);
