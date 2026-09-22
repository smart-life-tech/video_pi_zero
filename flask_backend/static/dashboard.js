const tokenInput = document.querySelector('#token');
const refreshButton = document.querySelector('#refresh');
const message = document.querySelector('#message');
const machineGrid = document.querySelector('#machines');
const total = document.querySelector('#total');
const online = document.querySelector('#online');
const attention = document.querySelector('#attention');
const updated = document.querySelector('#updated');
const adminPanel = document.querySelector('#admin-panel');
const adminResult = document.querySelector('#admin-result');
const seedForm = document.querySelector('#seed-form');
const codesForm = document.querySelector('#codes-form');
const seedMachineId = document.querySelector('#seed-machine-id');
const seedName = document.querySelector('#seed-name');
const seedSecret = document.querySelector('#seed-secret');
const seedKeyId = document.querySelector('#seed-key-id');
const codesMachineId = document.querySelector('#codes-machine-id');
const codesCount = document.querySelector('#codes-count');

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

function updateAdminVisibility(token) {
  const hasToken = Boolean(token);
  adminPanel.hidden = !hasToken;
  if (!hasToken) {
    adminResult.textContent = '';
  }
}

async function apiRequest(path, options = {}) {
  const token = tokenInput.value.trim();
  if (!token) {
    throw new Error('Enter the dashboard token first.');
  }

  const response = await fetch(path, {
    ...options,
    headers: {
      'X-Dashboard-Token': token,
      ...(options.headers || {})
    },
    cache: 'no-store'
  });

  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.error?.message || `Request failed (${response.status})`);
  }

  return body;
}

async function loadMachines() {
  const token = tokenInput.value.trim();
  if (!token) {
    message.textContent = 'Enter the dashboard token to begin monitoring.';
    updateAdminVisibility('');
    return;
  }

  updateAdminVisibility(token);
  sessionStorage.setItem('dashboardToken', token);
  message.textContent = 'Loading machine status...';
  try {
    const body = await apiRequest('/api/v1/dashboard/machines');
    renderMachines(body);
  } catch (error) {
    message.textContent = error.message;
    machineGrid.innerHTML = '';
  }
}

async function handleSeedMachine(event) {
  event.preventDefault();
  adminResult.textContent = 'Creating machine...';
  try {
    const machineId = seedMachineId.value.trim();
    const name = seedName.value.trim();
    const secret = seedSecret.value.trim();
    const keyId = seedKeyId.value;

    const body = await apiRequest('/api/v1/developer/machines', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ machineId, name, secret, keyId })
    });

    codesMachineId.value = machineId;
    seedMachineId.value = machineId;
    adminResult.textContent = JSON.stringify(body, null, 2);
    if (body.machineId) {
      message.textContent = `Machine ${body.machineId} ready.`;
    }
    await loadMachines();
  } catch (error) {
    adminResult.textContent = error.message;
  }
}

async function handleGenerateCodes(event) {
  event.preventDefault();
  adminResult.textContent = 'Generating pairing codes...';
  try {
    const machineId = codesMachineId.value.trim();
    const count = Number(codesCount.value || 1);

    const body = await apiRequest(`/api/v1/developer/machines/${encodeURIComponent(machineId)}/pairing-codes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ count })
    });

    seedMachineId.value = machineId;
    adminResult.textContent = JSON.stringify(body, null, 2);
    message.textContent = `Generated ${body.count} codes for ${machineId}.`;
  } catch (error) {
    adminResult.textContent = error.message;
  }
}

refreshButton.addEventListener('click', loadMachines);
tokenInput.addEventListener('keydown', event => {
  if (event.key === 'Enter') loadMachines();
});
seedForm.addEventListener('submit', handleSeedMachine);
codesForm.addEventListener('submit', handleGenerateCodes);
updateAdminVisibility(tokenInput.value.trim());
loadMachines();
setInterval(loadMachines, 30000);
