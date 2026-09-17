async function loadGuilds() {
  const response = await fetch('/api/guilds', {cache:'no-store'});
  if (response.status === 401 || response.status === 403) { location.href='/login'; return; }
  if (!response.ok) throw new Error('Unable to load servers');
  const data = await response.json();
  const select = document.getElementById('guild');
  select.innerHTML = data.guilds.map(g => `<option value="${g.id}">${escapeHtml(g.name)}</option>`).join('');
}
function escapeHtml(value) { return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
async function loadMatches() {
  const guild = document.getElementById('guild').value;
  const response = await fetch(`/api/matches?guild_id=${encodeURIComponent(guild)}&limit=200`, {cache:'no-store'});
  if (!response.ok) throw new Error('Unable to load matches');
  const data = await response.json();
  const term = document.getElementById('search').value.trim().toLowerCase();
  const rows = data.matches.filter(m => !term || m.challenger_id.toLowerCase().includes(term) || m.opponent_id.toLowerCase().includes(term));
  document.getElementById('count').textContent = `${rows.length} shown`;
  document.getElementById('matches').innerHTML = rows.length ? rows.map(m => `<tr><td><strong>${escapeHtml(m.id.slice(-12))}</strong><small>${escapeHtml(m.status)}</small></td><td>${escapeHtml(m.challenger_id)}</td><td>${escapeHtml(m.opponent_id)}</td><td>${m.season_number || '—'}</td><td>${m.courses_beat}/5</td><td>${m.challenger_won ? 'Challenger won' : 'Defense held'}</td></tr>`).join('') : '<tr><td colspan="6">No matches found.</td></tr>';
}
(async function(){ try { await loadGuilds(); await loadMatches(); document.getElementById('guild').addEventListener('change', loadMatches); document.getElementById('search').addEventListener('input', loadMatches); } catch (_) { document.getElementById('matches').innerHTML='<tr><td colspan="6">Unable to load match data.</td></tr>'; } })();
