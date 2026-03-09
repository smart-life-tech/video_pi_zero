const connectionBadge = document.getElementById('connectionBadge');

async function sendControl(slot, action) {
  const messageNode = document.getElementById(`message-${slot}`);
  const buttons = Array.from(document.querySelectorAll(`button[data-slot="${slot}"]`));

  buttons.forEach((btn) => {
    btn.disabled = true;
  });
  messageNode.textContent = `Sending ${action.toUpperCase()} command...`;

  try {
    const response = await fetch(`/api/slot/${slot}/${action}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: 'web_ui' }),
    });
    const payload = await response.json();
    if (!payload.ok) {
      throw new Error(payload.error || 'Unknown PLC write error');
    }

    messageNode.textContent = `${action.toUpperCase()} sent to coil ${payload.coil}`;
    await refreshStatus();
  } catch (err) {
    messageNode.textContent = `Error: ${err.message}`;
  } finally {
    buttons.forEach((btn) => {
      btn.disabled = false;
    });
  }
}

function updateSlotState(slotId, running) {
  const stateNode = document.getElementById(`state-${slotId}`);
  if (!stateNode) {
    return;
  }

  if (running) {
    stateNode.textContent = 'State: Running';
    stateNode.classList.add('state-running');
    stateNode.classList.remove('state-stopped');
  } else {
    stateNode.textContent = 'State: Stopped/Idle';
    stateNode.classList.add('state-stopped');
    stateNode.classList.remove('state-running');
  }
}

async function refreshStatus() {
  try {
    const response = await fetch('/api/status');
    const payload = await response.json();
    if (!payload.ok) {
      throw new Error(payload.error || 'Status read error');
    }

    connectionBadge.textContent = `PLC ${payload.modbus.server}:${payload.modbus.port}`;
    connectionBadge.classList.add('online');
    connectionBadge.classList.remove('offline');

    Object.entries(payload.slots).forEach(([slotId, slot]) => {
      updateSlotState(slotId, Boolean(slot.running));
    });
  } catch (err) {
    connectionBadge.textContent = `PLC Offline: ${err.message}`;
    connectionBadge.classList.add('offline');
    connectionBadge.classList.remove('online');
  }
}

document.querySelectorAll('button[data-action][data-slot]').forEach((button) => {
  button.addEventListener('click', async () => {
    const slot = button.dataset.slot;
    const action = button.dataset.action;
    await sendControl(slot, action);
  });
});

refreshStatus();
setInterval(refreshStatus, 1000);
