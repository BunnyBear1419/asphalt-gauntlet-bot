async function refreshStatus() {
  const pill = document.getElementById("system-pill");
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const online = data.bot.online;
    document.getElementById("bot-status").textContent = online ? "Online" : "Offline";
    document.getElementById("latency").textContent = data.bot.latency_ms == null ? "—" : `${data.bot.latency_ms} ms`;
    document.getElementById("guilds").textContent = data.bot.guild_count;
    pill.textContent = online ? "● Bot online" : "● Bot offline";
  } catch (error) {
    document.getElementById("bot-status").textContent = "Unavailable";
    document.getElementById("latency").textContent = "—";
    document.getElementById("guilds").textContent = "—";
    pill.textContent = "● Control center unavailable";
  }
}

refreshStatus();
setInterval(refreshStatus, 10000);
