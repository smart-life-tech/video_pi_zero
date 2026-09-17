const connectionBadge = document.getElementById('connectionBadge');
const videoCatalogNode = document.getElementById('videoCatalog');
const availableVideos = videoCatalogNode ? JSON.parse(videoCatalogNode.textContent) : [];

let isTestingAll = false;

function getSlotVideoElement(slot) {
  const slotSection = document.querySelector(`.slot[data-slot-id="${slot}"]`);
  return slotSection ? slotSection.querySelector('video.slot-video') : null;
}

function setSlotMessage(slot, text) {
  const messageNode = document.getElementById(`message-${slot}`);
  if (messageNode) {
    messageNode.textContent = text;
  }
}

async function testVideoOnSlot(slot, videoName) {
  const video = getSlotVideoElement(slot);
  if (!video) {
    return;
  }

  const source = video.querySelector('source');
  if (!source) {
    return;
  }

  source.src = `/videos/${videoName}`;
  video.load();
  try {
    await video.play();
  } catch {
    // Browser may block autoplay depending on environment.
  }
  setSlotMessage(slot, `Testing video: ${videoName}`);
}

async function testAllVideos() {
  if (isTestingAll) {
    return;
  }
  isTestingAll = true;

  if (!availableVideos.length) {
    Object.keys({ slot1: true, slot2: true }).forEach((slot) => {
      setSlotMessage(slot, 'No .mp4 files found for testing');
    });
    isTestingAll = false;
    return;
  }

  const slotIds = Array.from(document.querySelectorAll('.slot')).map((node) => node.dataset.slotId);
  for (const videoName of availableVideos) {
    for (const slotId of slotIds) {
      await testVideoOnSlot(slotId, videoName);
    }
    await new Promise((resolve) => setTimeout(resolve, 1800));
  }

  slotIds.forEach((slotId) => {
    setSlotMessage(slotId, 'Test All Videos complete');
  });
  isTestingAll = false;
}

async function sendControl(slot, action) {
  const buttons = Array.from(document.querySelectorAll(`button[data-slot="${slot}"]`));

  buttons.forEach((btn) => {
    btn.disabled = true;
  });
  setSlotMessage(slot, `Sending ${action.toUpperCase()} command...`);

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

    setSlotMessage(slot, `${action.toUpperCase()} sent to coil ${payload.coil}`);
    await refreshStatus();
  } catch (err) {
    setSlotMessage(slot, `Error: ${err.message}`);
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
    if (action === 'test-slot-video') {
      const response = await fetch('/api/status');
      const payload = await response.json();
      const videoName = payload?.slots?.[slot]?.video;
      if (videoName) {
        await testVideoOnSlot(slot, videoName);
      } else {
        setSlotMessage(slot, 'Could not determine slot video from API status');
      }
      return;
    }
    await sendControl(slot, action);
  });
});

const testAllBtn = document.getElementById('testAllBtn');
if (testAllBtn) {
  testAllBtn.addEventListener('click', async () => {
    testAllBtn.disabled = true;
    testAllBtn.textContent = 'Testing...';
    try {
      await testAllVideos();
    } finally {
      testAllBtn.disabled = false;
      testAllBtn.textContent = 'Test All Videos';
    }
  });
}

refreshStatus();
setInterval(refreshStatus, 1000);
