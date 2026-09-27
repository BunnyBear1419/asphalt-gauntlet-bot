(() => {
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmtTime = seconds => {
    const s = Math.max(0, Number(seconds || 0));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    return h ? h + "h " + m + "m" : m + "m";
  };
  async function api(url, options) {
    const r = await fetch(url, {credentials:"same-origin", ...(options || {})});
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || "Request failed");
    return d;
  }
  const state = { period:"all", me:null, rows:[], settings:null };
  function render() {
    const me = state.me || {};
    const p = Number(me.percent || 0);
    const rows = state.rows || [];
    const rank = rows.findIndex(r => String(r.user_id) === String(me.user_id)) + 1;
    document.getElementById("rsl-xp-card").innerHTML =
      '<div class="rank-badge">LEVEL '+esc(me.level ?? 0)+'</div>' +
      '<div><div class="rank-name">'+esc(me.name || "Driver")+'</div><div class="rank-meta">'+esc(me.xp || 0)+' XP • '+(rank > 0 ? '#'+rank : "Unranked")+'</div></div>' +
      '<div class="rank-progress"><span style="width:'+p+'%"></span></div>' +
      '<div class="rank-progress-label">'+esc(me.current_xp || 0)+' / '+esc(me.needed_xp || 0)+' to next level</div>';
    document.getElementById("xp-stats").innerHTML =
      '<div><b>'+esc(me.weekly_xp || 0)+'</b><span>Weekly XP</span></div><div><b>'+esc(me.monthly_xp || 0)+'</b><span>Monthly XP</span></div><div><b>'+esc(fmtTime(me.voice_seconds))+'</b><span>Voice</span></div><div><b>'+esc(me.reactions || 0)+'</b><span>Reactions</span></div>';
    document.getElementById("xp-leaderboard").innerHTML = rows.map(r =>
      '<div class="lb-row '+(String(r.user_id)===String(me.user_id) ? "mine":"")+'"><strong>#'+esc(r.rank)+'</strong><span class="lb-driver">'+esc(r.name)+'</span><span>Lv '+esc(r.level)+'</span><b>'+esc(r.xp)+' XP</b></div>'
    ).join("") || '<div class="empty">No XP rankings yet.</div>';
  }
  async function load(period) {
    state.period = period;
    document.querySelectorAll("[data-period]").forEach(b => b.classList.toggle("active", b.dataset.period === period));
    const [me, board, history] = await Promise.all([
      api("/api/xp/me"),
      api("/api/xp/leaderboard?period="+encodeURIComponent(period)),
      api("/api/xp/history")
    ]);
    state.me = me; state.rows = board.rows || [];
    render();
    document.getElementById("xp-history").innerHTML = (history.rows || []).slice(0,12).map(x =>
      '<div class="history-row"><span>'+esc(x.source)+'</span><b>+'+esc(x.amount)+'</b><small>'+esc((x.created_at || "").replace("T"," ").slice(0,19))+'</small></div>'
    ).join("") || '<div class="empty">Your XP activity history will appear here.</div>';
  }
  async function loadAdmin() {
    try {
      state.settings = await api("/api/xp/settings");
      const s = state.settings;
      document.getElementById("xp-admin").hidden = false;
      document.getElementById("xp-curve").value = s.curve || "linear";
      document.getElementById("xp-multiplier").value = s.multiplier ?? 1;
      document.getElementById("xp-max-level").value = s.max_level ?? 0;
      document.getElementById("xp-message-min").value = s.message_min ?? 15;
      document.getElementById("xp-message-max").value = s.message_max ?? 30;
      document.getElementById("xp-message-cooldown").value = s.message_cooldown ?? 60;
      document.getElementById("xp-voice-xp").value = s.voice_xp ?? 10;
      document.getElementById("xp-reaction-xp").value = s.reaction_xp ?? 5;
      document.getElementById("xp-voice-min").value = s.voice_min_members ?? 2;
      document.getElementById("xp-role-rewards").value = (s.role_rewards || []).map(x => (x.level || "") + ":" + (x.role_id || "")).join("\n");
      document.getElementById("xp-excluded-roles").value = (s.excluded_role_ids || []).join("\n");
      document.getElementById("xp-excluded-channels").value = (s.excluded_channel_ids || []).join("\n");
      document.getElementById("xp-allowed-channels").value = (s.allowed_channel_ids || []).join("\n");
    } catch (_) {}
  }
  async function saveAdmin() {
    const lines = id => document.getElementById(id).value.split(/\s+/).map(x=>x.trim()).filter(Boolean);
    const rewards = document.getElementById("xp-role-rewards").value.split(/\n+/).map(x=>x.trim()).filter(Boolean).map(x => {
      const [level, role_id] = x.split(":"); return {level:Number(level||0), role_id:String(role_id||"")};
    }).filter(x=>x.level>0 && x.role_id);
    const payload = {
      curve:document.getElementById("xp-curve").value,
      multiplier:Number(document.getElementById("xp-multiplier").value || 1),
      max_level:Number(document.getElementById("xp-max-level").value || 0),
      message_min:Number(document.getElementById("xp-message-min").value || 15),
      message_max:Number(document.getElementById("xp-message-max").value || 30),
      message_cooldown:Number(document.getElementById("xp-message-cooldown").value || 60),
      voice_xp:Number(document.getElementById("xp-voice-xp").value || 10),
      reaction_xp:Number(document.getElementById("xp-reaction-xp").value || 5),
      voice_min_members:Number(document.getElementById("xp-voice-min").value || 2),
      role_rewards:rewards,
      excluded_role_ids:lines("xp-excluded-roles"),
      excluded_channel_ids:lines("xp-excluded-channels"),
      allowed_channel_ids:lines("xp-allowed-channels")
    };
    await api("/api/xp/settings",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    document.getElementById("xp-admin-status").textContent="XP settings saved.";
  }
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-period]").forEach(b => b.addEventListener("click", () => load(b.dataset.period)));
    document.getElementById("xp-admin-save")?.addEventListener("click", saveAdmin);
    load("all").catch(e => { document.getElementById("xp-error").textContent = e.message; });
    loadAdmin();
  });
})();