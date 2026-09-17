async function loadLogs(){
  const status=document.getElementById('logs-status');
  try{
    const gs=await fetch('/api/guilds');
    if(gs.status===401||gs.status===403){location.href='/login';return;}
    const data=await gs.json(); const select=document.getElementById('guild-select');
    select.innerHTML=data.guilds.map(g=>`<option value="${escapeHtml(g.id)}">${escapeHtml(g.name)}</option>`).join('');
    if(!data.guilds.length){status.textContent='No Discord servers are available for your staff account.';return;}
    select.onchange=refresh; await refresh();
  }catch(e){status.textContent='Unable to load audit data.';}
  async function refresh(){
    status.textContent='Loading audit events…';
    const r=await fetch(`/api/logs?guild_id=${encodeURIComponent(select.value)}&limit=200`);
    if(r.status===401||r.status===403){location.href='/login';return;}
    const d=await r.json(); const rows=d.logs||[];
    document.getElementById('event-count').textContent=rows.length;
    document.getElementById('admin-count').textContent=rows.filter(x=>x.type==='admin').length;
    document.getElementById('system-count').textContent=rows.filter(x=>x.type==='system').length;
    document.getElementById('logs-body').innerHTML=rows.length?rows.map(x=>`<tr><td>${escapeHtml(formatTime(x.timestamp))}</td><td>${escapeHtml(x.type)}</td><td><b>${escapeHtml(x.action)}</b></td><td>${escapeHtml(x.details||'')}</td></tr>`).join(''):`<tr><td colspan="4">No recorded audit events found.</td></tr>`;
    status.textContent=`Showing ${rows.length} recent event${rows.length===1?'':'s'}.`;
  }
}
function formatTime(v){if(!v)return '—';const d=new Date(v);return Number.isNaN(d.getTime())?String(v):d.toLocaleString();}
function escapeHtml(v){return String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));}
loadLogs();
