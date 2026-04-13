// @ts-check
/// <reference path="../node_modules/@types/vscode-webview/index.d.ts" />

/**
 * Arize Setup Wizard — Webview Script
 *
 * Four-step wizard: Harness → Backend → Options → Summary/Install
 */

(function () {
  "use strict";

  // -------------------------------------------------------------------------
  // VS Code API
  // -------------------------------------------------------------------------

  // @ts-ignore — acquireVsCodeApi is injected by the VS Code webview host
  const vscode = acquireVsCodeApi();

  // -------------------------------------------------------------------------
  // State
  // -------------------------------------------------------------------------

  const state = {
    currentStep: 1,
    harness: "",
    backend: "",
    credentials: /** @type {Record<string, string>} */ ({}),
    userId: "",
    scope: "project",
    ideDetection: /** @type {Record<string, boolean>} */ ({}),
    installing: false,
  };

  const TOTAL_STEPS = 4;

  const STEP_TITLES = [
    "Choose Harness",
    "Select Backend",
    "Options",
    "Review & Install",
  ];

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  function render() {
    const root = document.getElementById("wizard-root");
    if (!root) { return; }

    root.innerHTML = `
      ${renderProgressBar()}
      ${renderStep1()}
      ${renderStep2()}
      ${renderStep3()}
      ${renderStep4()}
      ${renderNavButtons()}
    `;

    attachListeners();
  }

  // -------------------------------------------------------------------------
  // Progress bar
  // -------------------------------------------------------------------------

  function renderProgressBar() {
    let html = '<div class="progress-bar">';
    for (let i = 1; i <= TOTAL_STEPS; i++) {
      const cls = i === state.currentStep ? "active" : i < state.currentStep ? "completed" : "";
      const label = STEP_TITLES[i - 1];
      const checkmark = i < state.currentStep ? "✓" : String(i);
      html += `
        <div class="progress-step ${cls}">
          <span class="step-number">${checkmark}</span>
          <span class="step-label">Step ${i} — ${label}</span>
        </div>`;
      if (i < TOTAL_STEPS) {
        const connCls = i < state.currentStep ? "completed" : "";
        html += `<div class="progress-connector ${connCls}"></div>`;
      }
    }
    html += "</div>";
    return html;
  }

  // -------------------------------------------------------------------------
  // Step 1 — Choose Harness
  // -------------------------------------------------------------------------

  function renderStep1() {
    const active = state.currentStep === 1 ? "active" : "";
    const harnesses = [
      {
        id: "claude",
        title: "Claude Code",
        icon: "🤖",
        desc: "Anthropic's Claude Code CLI — hooks-based tracing via settings.json",
      },
      {
        id: "codex",
        title: "Codex",
        icon: "📦",
        desc: "OpenAI Codex CLI — proxy-based tracing via config.toml",
      },
      {
        id: "cursor",
        title: "Cursor",
        icon: "⚡",
        desc: "Cursor IDE — hooks-based tracing via hooks.json",
      },
    ];

    let cards = "";
    for (const h of harnesses) {
      const sel = state.harness === h.id ? "selected" : "";
      const detected = state.ideDetection[h.id] ? '<span class="badge">Detected</span>' : "";
      cards += `
        <div class="card ${sel}" data-harness="${h.id}">
          ${detected}
          <div class="card-icon">${h.icon}</div>
          <div class="card-title">${h.title}</div>
          <div class="card-desc">${h.desc}</div>
        </div>`;
    }

    return `
      <div class="step ${active}" id="step-1">
        <h2>Choose Harness</h2>
        <p class="step-description">Select which AI coding harness you want to set up tracing for.</p>
        <div class="card-grid">${cards}</div>
      </div>`;
  }

  // -------------------------------------------------------------------------
  // Step 2 — Select Backend
  // -------------------------------------------------------------------------

  function renderStep2() {
    const active = state.currentStep === 2 ? "active" : "";
    const backends = [
      {
        id: "phoenix",
        title: "Phoenix",
        icon: "🔥",
        desc: "Open-source observability — local or self-hosted",
      },
      {
        id: "arize",
        title: "Arize AX",
        icon: "📊",
        desc: "Arize cloud platform — managed observability",
      },
    ];

    let cards = "";
    for (const b of backends) {
      const sel = state.backend === b.id ? "selected" : "";
      cards += `
        <div class="card ${sel}" data-backend="${b.id}">
          <div class="card-icon">${b.icon}</div>
          <div class="card-title">${b.title}</div>
          <div class="card-desc">${b.desc}</div>
        </div>`;
    }

    // Phoenix fields
    const phoenixVisible = state.backend === "phoenix" ? "visible" : "";
    const phoenixEndpoint = state.credentials.phoenixEndpoint || "";

    // Arize fields
    const arizeVisible = state.backend === "arize" ? "visible" : "";
    const apiKey = state.credentials.apiKey || "";
    const spaceId = state.credentials.spaceId || "";
    const otlpEndpoint = state.credentials.otlpEndpoint || "";

    return `
      <div class="step ${active}" id="step-2">
        <h2>Select Backend</h2>
        <p class="step-description">Choose where trace data should be sent.</p>
        <div class="card-grid">${cards}</div>

        <div class="credential-fields ${phoenixVisible}" id="phoenix-fields">
          <div class="field-group">
            <label>Phoenix Endpoint</label>
            <input type="text" id="phoenix-endpoint" value="${escapeAttr(phoenixEndpoint)}"
              placeholder="http://localhost:6006" />
            <div class="field-hint">Leave empty for default (http://localhost:6006)</div>
          </div>
        </div>

        <div class="credential-fields ${arizeVisible}" id="arize-fields">
          <div class="field-group">
            <label>API Key <span class="required">*</span></label>
            <input type="password" id="arize-api-key" value="${escapeAttr(apiKey)}"
              placeholder="Enter your Arize API key" />
          </div>
          <div class="field-group">
            <label>Space ID <span class="required">*</span></label>
            <input type="text" id="arize-space-id" value="${escapeAttr(spaceId)}"
              placeholder="Enter your Arize Space ID" />
          </div>
          <div class="field-group">
            <label>OTLP Endpoint</label>
            <input type="text" id="arize-otlp-endpoint" value="${escapeAttr(otlpEndpoint)}"
              placeholder="https://otlp.arize.com" />
            <div class="field-hint">Leave empty for default (https://otlp.arize.com)</div>
          </div>
        </div>
      </div>`;
  }

  // -------------------------------------------------------------------------
  // Step 3 — Options
  // -------------------------------------------------------------------------

  function renderStep3() {
    const active = state.currentStep === 3 ? "active" : "";
    const userId = state.userId || "";

    const isClaude = state.harness === "claude";
    const scopeProject = state.scope === "project" ? "checked" : "";
    const scopeGlobal = state.scope === "global" ? "checked" : "";

    let scopeHtml = "";
    if (isClaude) {
      scopeHtml = `
        <div class="field-group">
          <label>Settings Scope</label>
          <div class="radio-group">
            <label class="radio-option">
              <input type="radio" name="scope" value="project" ${scopeProject} />
              <div>
                <div class="radio-label">Project-local</div>
                <div class="radio-desc">Hooks are added to the current project's .claude/settings.json</div>
              </div>
            </label>
            <label class="radio-option">
              <input type="radio" name="scope" value="global" ${scopeGlobal} />
              <div>
                <div class="radio-label">Global</div>
                <div class="radio-desc">Hooks are added to your global Claude Code settings</div>
              </div>
            </label>
          </div>
        </div>`;
    }

    return `
      <div class="step ${active}" id="step-3">
        <h2>Options</h2>
        <p class="step-description">Configure optional settings.</p>
        <div class="field-group">
          <label>User ID</label>
          <input type="text" id="user-id" value="${escapeAttr(userId)}"
            placeholder="Optional — identifies you in traces" />
          <div class="field-hint">Used to tag traces with your identity. Leave blank for default.</div>
        </div>
        ${scopeHtml}
      </div>`;
  }

  // -------------------------------------------------------------------------
  // Step 4 — Review & Install
  // -------------------------------------------------------------------------

  function renderStep4() {
    const active = state.currentStep === 4 ? "active" : "";

    const harnessLabel = { claude: "Claude Code", codex: "Codex", cursor: "Cursor" }[state.harness] || state.harness;
    const backendLabel = { phoenix: "Phoenix", arize: "Arize AX" }[state.backend] || state.backend;

    let credRows = "";
    if (state.backend === "phoenix" && state.credentials.phoenixEndpoint) {
      credRows += summaryRow("Phoenix Endpoint", state.credentials.phoenixEndpoint);
    }
    if (state.backend === "arize") {
      if (state.credentials.apiKey) {
        credRows += summaryRow("API Key", "••••" + state.credentials.apiKey.slice(-4));
      }
      if (state.credentials.spaceId) {
        credRows += summaryRow("Space ID", state.credentials.spaceId);
      }
      if (state.credentials.otlpEndpoint) {
        credRows += summaryRow("OTLP Endpoint", state.credentials.otlpEndpoint);
      }
    }

    const spinnerVis = state.installing ? "visible" : "";
    const installDisabled = state.installing ? "disabled" : "";

    return `
      <div class="step ${active}" id="step-4">
        <h2>Review & Install</h2>
        <p class="step-description">Review your selections and start the installation.</p>
        <table class="summary-table">
          <tbody>
            ${summaryRow("Harness", harnessLabel)}
            ${summaryRow("Backend", backendLabel)}
            ${credRows}
            ${state.userId ? summaryRow("User ID", state.userId) : ""}
            ${state.harness === "claude" ? summaryRow("Scope", state.scope) : ""}
          </tbody>
        </table>

        <button class="primary" id="btn-install" ${installDisabled}>Install</button>

        <div class="spinner ${spinnerVis}" id="spinner">
          <div class="spinner-icon"></div>
          <span>Installing…</span>
        </div>

        <div class="status-message" id="status-success">
          <span class="status-icon">✅</span>
          <div>
            <strong>Installation complete!</strong>
            <p>Tracing is now configured for ${harnessLabel}. You can close this wizard.</p>
          </div>
        </div>

        <div class="status-message" id="status-error">
          <span class="status-icon">❌</span>
          <div>
            <strong>Installation failed</strong>
            <p id="error-detail"></p>
          </div>
        </div>

        <div class="output-log-container">
          <div class="output-log-toggle" id="log-toggle">▶ Show install log</div>
          <div class="output-log" id="output-log"></div>
        </div>
      </div>`;
  }

  function summaryRow(label, value) {
    return `<tr><th>${escapeHtml(label)}</th><td>${escapeHtml(value)}</td></tr>`;
  }

  // -------------------------------------------------------------------------
  // Navigation buttons
  // -------------------------------------------------------------------------

  function renderNavButtons() {
    const isFirst = state.currentStep === 1;
    const isLast = state.currentStep === TOTAL_STEPS;
    const nextDisabled = !canAdvance() ? "disabled" : "";

    // Skip step 3 for non-Claude when going to "Next"
    const backHidden = isFirst ? 'style="visibility:hidden"' : "";

    return `
      <div class="nav-buttons">
        <button class="secondary" id="btn-back" ${backHidden}>Back</button>
        <div class="spacer"></div>
        <button class="link-button" id="btn-cancel">Cancel</button>
        ${!isLast ? `<button class="primary" id="btn-next" ${nextDisabled}>Next</button>` : ""}
      </div>`;
  }

  // -------------------------------------------------------------------------
  // Validation
  // -------------------------------------------------------------------------

  function canAdvance() {
    switch (state.currentStep) {
      case 1:
        return state.harness !== "";
      case 2:
        if (!state.backend) { return false; }
        if (state.backend === "arize") {
          return (state.credentials.apiKey || "").trim() !== ""
            && (state.credentials.spaceId || "").trim() !== "";
        }
        return true;
      case 3:
        return true; // No required fields
      case 4:
        return true;
      default:
        return false;
    }
  }

  /**
   * Determine the next step, skipping step 3 for non-Claude harnesses.
   */
  function nextStep() {
    if (state.currentStep === 2 && state.harness !== "claude") {
      return 4; // Skip options step
    }
    return state.currentStep + 1;
  }

  /**
   * Determine the previous step, skipping step 3 for non-Claude harnesses.
   */
  function prevStep() {
    if (state.currentStep === 4 && state.harness !== "claude") {
      return 2; // Skip options step going back
    }
    return state.currentStep - 1;
  }

  // -------------------------------------------------------------------------
  // Read credential fields from DOM into state
  // -------------------------------------------------------------------------

  function syncCredentials() {
    if (state.currentStep === 2) {
      if (state.backend === "phoenix") {
        const el = document.getElementById("phoenix-endpoint");
        if (el) { state.credentials.phoenixEndpoint = el.value; }
      } else if (state.backend === "arize") {
        const apiKeyEl = document.getElementById("arize-api-key");
        const spaceIdEl = document.getElementById("arize-space-id");
        const otlpEl = document.getElementById("arize-otlp-endpoint");
        if (apiKeyEl) { state.credentials.apiKey = apiKeyEl.value; }
        if (spaceIdEl) { state.credentials.spaceId = spaceIdEl.value; }
        if (otlpEl) { state.credentials.otlpEndpoint = otlpEl.value; }
      }
    }
    if (state.currentStep === 3) {
      const userIdEl = document.getElementById("user-id");
      if (userIdEl) { state.userId = userIdEl.value; }
      const scopeEl = document.querySelector('input[name="scope"]:checked');
      if (scopeEl) { state.scope = scopeEl.value; }
    }
  }

  // -------------------------------------------------------------------------
  // Event listeners
  // -------------------------------------------------------------------------

  function attachListeners() {
    // Harness cards
    document.querySelectorAll("[data-harness]").forEach(function (card) {
      card.addEventListener("click", function () {
        state.harness = card.getAttribute("data-harness") || "";
        render();
      });
    });

    // Backend cards
    document.querySelectorAll("[data-backend]").forEach(function (card) {
      card.addEventListener("click", function () {
        syncCredentials();
        state.backend = card.getAttribute("data-backend") || "";
        render();
      });
    });

    // Credential inputs — update validation state on input
    document.querySelectorAll("#arize-fields input, #phoenix-fields input").forEach(function (input) {
      input.addEventListener("input", function () {
        syncCredentials();
        // Update Next button enabled state
        var nextBtn = document.getElementById("btn-next");
        if (nextBtn) {
          nextBtn.disabled = !canAdvance();
        }
      });
    });

    // Navigation
    var btnNext = document.getElementById("btn-next");
    if (btnNext) {
      btnNext.addEventListener("click", function () {
        syncCredentials();
        if (canAdvance()) {
          state.currentStep = nextStep();
          render();
        }
      });
    }

    var btnBack = document.getElementById("btn-back");
    if (btnBack) {
      btnBack.addEventListener("click", function () {
        syncCredentials();
        state.currentStep = prevStep();
        render();
      });
    }

    var btnCancel = document.getElementById("btn-cancel");
    if (btnCancel) {
      btnCancel.addEventListener("click", function () {
        vscode.postMessage({ type: "cancel" });
      });
    }

    // Install button
    var btnInstall = document.getElementById("btn-install");
    if (btnInstall) {
      btnInstall.addEventListener("click", function () {
        startInstall();
      });
    }

    // Log toggle
    var logToggle = document.getElementById("log-toggle");
    if (logToggle) {
      logToggle.addEventListener("click", function () {
        var log = document.getElementById("output-log");
        if (log) {
          var isVisible = log.classList.contains("visible");
          log.classList.toggle("visible");
          logToggle.textContent = isVisible ? "▶ Show install log" : "▼ Hide install log";
        }
      });
    }
  }

  // -------------------------------------------------------------------------
  // Install
  // -------------------------------------------------------------------------

  function startInstall() {
    state.installing = true;

    // Update UI without full re-render to preserve log
    var btnInstall = document.getElementById("btn-install");
    if (btnInstall) { btnInstall.disabled = true; }
    var spinner = document.getElementById("spinner");
    if (spinner) { spinner.classList.add("visible"); }

    // Show log automatically
    var log = document.getElementById("output-log");
    if (log) { log.classList.add("visible"); }
    var logToggle = document.getElementById("log-toggle");
    if (logToggle) { logToggle.textContent = "▼ Hide install log"; }

    vscode.postMessage({
      type: "install",
      harness: state.harness,
      backend: state.backend,
      credentials: state.credentials,
      userId: state.userId,
      scope: state.scope,
    });
  }

  // -------------------------------------------------------------------------
  // Messages from extension
  // -------------------------------------------------------------------------

  window.addEventListener("message", function (event) {
    var msg = event.data;

    switch (msg.type) {
      case "output":
        appendLog(msg.line);
        break;

      case "complete":
        state.installing = false;
        var spinner = document.getElementById("spinner");
        if (spinner) { spinner.classList.remove("visible"); }

        if (msg.success) {
          var successEl = document.getElementById("status-success");
          if (successEl) { successEl.classList.add("visible", "success"); }
        } else {
          var errorEl = document.getElementById("status-error");
          if (errorEl) { errorEl.classList.add("visible", "error"); }
          var detail = document.getElementById("error-detail");
          if (detail) { detail.textContent = msg.error || "Unknown error"; }
        }

        var btnInstall = document.getElementById("btn-install");
        if (btnInstall) { btnInstall.disabled = false; btnInstall.textContent = msg.success ? "Done" : "Retry"; }
        break;

      case "ideDetection":
        state.ideDetection = msg.results || {};
        render();
        break;

      case "prefill":
        if (msg.harness) { state.harness = msg.harness; }
        if (msg.backend) { state.backend = msg.backend; }
        if (msg.credentials) { state.credentials = msg.credentials; }
        if (msg.userId) { state.userId = msg.userId; }
        if (msg.scope) { state.scope = msg.scope; }
        render();
        break;
    }
  });

  function appendLog(text) {
    var log = document.getElementById("output-log");
    if (!log) { return; }
    log.textContent += text;
    log.scrollTop = log.scrollHeight;
  }

  // -------------------------------------------------------------------------
  // Helpers
  // -------------------------------------------------------------------------

  function escapeHtml(str) {
    var div = document.createElement("div");
    div.textContent = str || "";
    return div.innerHTML;
  }

  function escapeAttr(str) {
    return (str || "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // -------------------------------------------------------------------------
  // Init
  // -------------------------------------------------------------------------

  render();

  // Request IDE detection from extension
  vscode.postMessage({ type: "detectIdes" });
})();
