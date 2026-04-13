// @ts-check
/// <reference lib="dom" />

/**
 * Sidebar webview script.
 *
 * Receives `{ type: 'state', collector, backend, harnesses }` messages from
 * the extension host and renders the harness list. Sends action messages
 * back on button clicks.
 */
(function () {
  // eslint-disable-next-line no-undef
  const vscode = acquireVsCodeApi();

  const collectorStatus = document.getElementById("collector-status");
  const collectorDot = document.getElementById("collector-dot");
  const collectorLabel = document.getElementById("collector-label");
  const backendRow = document.getElementById("backend-row");
  const harnessList = document.getElementById("harness-list");
  const emptyState = document.getElementById("empty-state");
  const addBtn = document.getElementById("add-btn");

  // -------------------------------------------------------------------------
  // Rendering
  // -------------------------------------------------------------------------

  /**
   * Render the full sidebar state.
   * @param {{ collector: { running: boolean, port: number }, backend: string, harnesses: Array<{ name: string, project: string }> }} state
   */
  function renderState(state) {
    // Collector status
    var running = state.collector && state.collector.running;
    collectorDot.className = "dot " + (running ? "running" : "stopped");
    collectorLabel.textContent = running ? "Running" : "Stopped";
    collectorStatus.title = running
      ? "Click to stop collector"
      : "Click to start collector";

    // Backend
    var backend = state.backend || "none";
    backendRow.textContent =
      "Backend: " + (backend === "none" ? "\u2014" : backend);

    // Harnesses
    harnessList.innerHTML = "";
    var harnesses = state.harnesses || [];

    if (harnesses.length === 0) {
      emptyState.style.display = "block";
    } else {
      emptyState.style.display = "none";
      harnesses.forEach(function (h) {
        var card = document.createElement("div");
        card.className = "harness-card";

        var name = document.createElement("div");
        name.className = "harness-name";
        name.textContent = h.name;
        card.appendChild(name);

        var project = document.createElement("div");
        project.className = "harness-project";
        project.textContent = "Project: " + h.project;
        card.appendChild(project);

        var actions = document.createElement("div");
        actions.className = "harness-actions";

        var reconfigureBtn = document.createElement("button");
        reconfigureBtn.className = "action-btn";
        reconfigureBtn.textContent = "Reconfigure";
        reconfigureBtn.addEventListener("click", function (e) {
          e.stopPropagation();
          vscode.postMessage({ type: "reconfigure", harness: h.name });
        });
        actions.appendChild(reconfigureBtn);

        var removeBtn = document.createElement("button");
        removeBtn.className = "action-btn";
        removeBtn.textContent = "Remove";
        removeBtn.addEventListener("click", function (e) {
          e.stopPropagation();
          vscode.postMessage({ type: "remove", harness: h.name });
        });
        actions.appendChild(removeBtn);

        card.appendChild(actions);
        harnessList.appendChild(card);
      });
    }
  }

  // -------------------------------------------------------------------------
  // Event handlers
  // -------------------------------------------------------------------------

  // Collector toggle
  collectorStatus.addEventListener("click", function () {
    var isRunning = collectorDot.classList.contains("running");
    vscode.postMessage({
      type: isRunning ? "stopCollector" : "startCollector",
    });
  });

  // Add harness
  addBtn.addEventListener("click", function () {
    vscode.postMessage({ type: "addHarness" });
  });

  // Listen for state updates from extension host
  window.addEventListener("message", function (event) {
    var msg = event.data;
    if (msg.type === "state") {
      renderState(msg);
    }
  });
})();
