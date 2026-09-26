const elements = {
  connectionPill: document.getElementById("connection-pill"),
  connectionText: document.getElementById("connection-text"),
  commandGrid: document.getElementById("command-grid"),
  lastCommand: document.getElementById("last-command"),
  lastStatus: document.getElementById("last-status"),
  transportDevice: document.getElementById("transport-device"),
  activityLog: document.getElementById("activity-log"),
  refreshButton: document.getElementById("refresh-button"),
};

let commandCache = [];

function appendLog(message) {
  const timestamp = new Date().toLocaleTimeString();
  const existing = elements.activityLog.textContent.trim();
  const next = `[${timestamp}] ${message}`;
  elements.activityLog.textContent = existing && existing !== "Waiting for commands…"
    ? `${next}\n${existing}`
    : next;
}

function renderCommands(commands) {
  commandCache = commands;
  elements.commandGrid.innerHTML = "";

  commands.forEach((command) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `command-button ${command.variant || "primary"}`;
    button.innerHTML = `
      <span class="command-label">${command.label}</span>
      <span class="command-meta">${command.target} · ${command.action}</span>
    `;
    button.addEventListener("click", () => sendCommand(command.command, button));
    elements.commandGrid.appendChild(button);
  });
}

function updateStatus(status) {
  const transport = status.meshtastic;
  const connected = !!transport.connected;

  elements.connectionPill.classList.toggle("connected", connected);
  elements.connectionPill.classList.toggle("disconnected", !connected);
  elements.connectionText.textContent = connected
    ? `Connected${transport.mock_mode ? " (mock)" : ""}`
    : `Disconnected${transport.last_error ? ` — ${transport.last_error}` : ""}`;
  elements.lastCommand.textContent = status.last_command || "—";
  elements.lastStatus.textContent = status.last_command_status || "idle";
  elements.transportDevice.textContent = transport.device || `${transport.host || "—"}${transport.port ? `:${transport.port}` : ""}`;

  if (!commandCache.length && Array.isArray(status.available_commands)) {
    renderCommands(status.available_commands);
  }
}

async function fetchStatus() {
  const response = await fetch("/api/status");
  if (!response.ok) {
    throw new Error(`Status request failed (${response.status})`);
  }
  return response.json();
}

async function fetchCommands() {
  const response = await fetch("/api/commands");
  if (!response.ok) {
    throw new Error(`Commands request failed (${response.status})`);
  }
  const payload = await response.json();
  return payload.commands || [];
}

async function refreshAll() {
  try {
    const [status, commands] = await Promise.all([fetchStatus(), fetchCommands()]);
    renderCommands(commands);
    updateStatus(status);
  } catch (error) {
    elements.connectionPill.classList.add("disconnected");
    elements.connectionText.textContent = `Disconnected — ${error.message}`;
    appendLog(`Refresh failed: ${error.message}`);
  }
}

async function sendCommand(commandName, button) {
  const buttons = Array.from(document.querySelectorAll(".command-button"));
  buttons.forEach((item) => { item.disabled = true; });
  const original = button.innerHTML;
  button.innerHTML = `<span class="command-label">Sending…</span>`;

  try {
    const response = await fetch("/api/commands", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: commandName }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || `Command failed (${response.status})`);
    }

    elements.lastCommand.textContent = payload.command;
    elements.lastStatus.textContent = payload.status;
    appendLog(`${payload.command} → ${payload.status}`);
    await refreshAll();
  } catch (error) {
    elements.lastCommand.textContent = commandName;
    elements.lastStatus.textContent = "error";
    appendLog(`${commandName} failed: ${error.message}`);
  } finally {
    button.innerHTML = original;
    buttons.forEach((item) => { item.disabled = false; });
  }
}

elements.refreshButton.addEventListener("click", refreshAll);
refreshAll();
setInterval(refreshAll, 15000);
