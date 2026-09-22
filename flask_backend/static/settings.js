const tokenInput = document.querySelector('#token');
const adminResult = document.querySelector('#admin-result');
const seedForm = document.querySelector('#seed-form');
const codesForm = document.querySelector('#codes-form');
const deleteForm = document.querySelector('#delete-form');
const seedMachineId = document.querySelector('#seed-machine-id');
const seedName = document.querySelector('#seed-name');
const seedSecret = document.querySelector('#seed-secret');
const seedKeyId = document.querySelector('#seed-key-id');
const codesMachineId = document.querySelector('#codes-machine-id');
const codesCount = document.querySelector('#codes-count');
const deleteMachineId = document.querySelector('#delete-machine-id');

const savedToken = sessionStorage.getItem('dashboardToken');
if (savedToken) tokenInput.value = savedToken;

function ensureToken() {
  const token = tokenInput.value.trim();
  if (!token) {
    throw new Error('Enter the dashboard token to unlock the developer controls.');
  }
  sessionStorage.setItem('dashboardToken', token);
  return token;
}

async function apiRequest(path, options = {}) {
  const token = ensureToken();
  const response = await fetch(path, {
    ...options,
    headers: {
      'X-Dashboard-Token': token,
      ...(options.headers || {}),
    },
    cache: 'no-store'
  });

  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.error?.message || `Request failed (${response.status})`);
  }

  return body;
}

async function handleSeedMachine(event) {
  event.preventDefault();
  adminResult.textContent = 'Creating machine...';
  try {
    const payload = {
      machineId: seedMachineId.value.trim(),
      name: seedName.value.trim(),
      secret: seedSecret.value.trim(),
      keyId: seedKeyId.value
    };

    const body = await apiRequest('/api/v1/developer/machines', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    codesMachineId.value = payload.machineId;
    deleteMachineId.value = payload.machineId;
    adminResult.textContent = JSON.stringify(body, null, 2);
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
    deleteMachineId.value = machineId;
    adminResult.textContent = JSON.stringify(body, null, 2);
  } catch (error) {
    adminResult.textContent = error.message;
  }
}

async function handleDeleteMachine(event) {
  event.preventDefault();
  adminResult.textContent = 'Deleting machine...';
  try {
    const machineId = deleteMachineId.value.trim();
    const body = await apiRequest(`/api/v1/developer/machines/${encodeURIComponent(machineId)}`, {
      method: 'DELETE'
    });

    adminResult.textContent = JSON.stringify(body, null, 2);
    if (body.deleted) {
      codesMachineId.value = '';
      seedMachineId.value = 'hw-000123';
      seedName.value = 'Test Machine';
      seedSecret.value = 'MY_DEVICE_SECRET';
      deleteMachineId.value = 'hw-000123';
    }
  } catch (error) {
    adminResult.textContent = error.message;
  }
}

seedForm.addEventListener('submit', handleSeedMachine);
codesForm.addEventListener('submit', handleGenerateCodes);
deleteForm.addEventListener('submit', handleDeleteMachine);
