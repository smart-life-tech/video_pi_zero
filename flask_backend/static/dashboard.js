const tokenInput = document.querySelector('#token');
const refreshButton = document.querySelector('#refresh');
const message = document.querySelector('#message');
const machineGrid = document.querySelector('#machines');
const total = document.querySelector('#total');
const online = document.querySelector('#online');
const attention = document.querySelector('#attention');
const updated = document.querySelector('#updated');

const savedToken = sessionStorage.getItem('dashboardToken');
if (savedToken) tokenInput.value = savedToken;

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[character]));
}

function formatTime(value) {
  if (!value) return 'No heartbeat received';
  return new Date(value).toLocaleString();
}

function renderMachines(data) {
  const machines = data.machines || [];
  total.textContent = machines.length;
  online.textContent = machines.filter(machine => machine.signal === 'online').length;
  attention.textContent = machines.filter(machine => machine.signal === 'offline' || machine.state !== 'ok').length;
  updated.textContent = `Updated ${formatTime(data.serverTime)}`;
  message.textContent = machines.length ? '' : 'No provisioned machines found.';

  machineGrid.innerHTML = machines.map(machine => {
    const percent = machine.percentAvailable ? `${escapeHtml(machine.percent)}%` : '—';
    const signal = escapeHtml(machine.signal);
    const state = escapeHtml(machine.state);
    const signalAge = machine.secondsSinceSeen == null ? 'No heartbeat received' : `${machine.secondsSinceSeen}s since heartbeat`;
    return `<article class="machine">
      <div class="machine-head">
        <div><h2>${escapeHtml(machine.name)}</h2><p class="machine-id">${escapeHtml(machine.machineId)}</p></div>
        <span class="badge ${signal}">${signal}</span>
      </div>
      <div class="reading">
        <span class="state state-${state}">${state}</span>
        <strong class="percent">${percent}</strong>
      </div>
      <p class="meta">Last seen: ${escapeHtml(formatTime(machine.lastSeenAt))}<br>${escapeHtml(signalAge)}</p>
    </article>`;
  }).join('');
}

async function loadMachines() {
  const token = tokenInput.value.trim();
  if (!token) {
    message.textContent = 'Enter the dashboard token to begin monitoring.';
    return;
  }
  sessionStorage.setItem('dashboardToken', token);
  message.textContent = 'Loading machine status...';
  try {
    const response = await fetch('/api/v1/dashboard/machines', {
      headers: { 'X-Dashboard-Token': token },
      cache: 'no-store'
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error?.message || `Request failed (${response.status})`);
    renderMachines(body);
  } catch (error) {
    message.textContent = error.message;
    machineGrid.innerHTML = '';
  }
}

refreshButton.addEventListener('click', loadMachines);
tokenInput.addEventListener('keydown', event => {
  if (event.key === 'Enter') loadMachines();
});
loadMachines();
setInterval(loadMachines, 30000);
