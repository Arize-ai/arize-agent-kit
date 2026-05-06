/**
 * @jest-environment jsdom
 */

const fs = require("fs");
const path = require("path");

const HARNESS_KEYS = ["claude-code", "codex", "cursor", "copilot", "gemini"];

let postMessageCalls;

function setupWizard() {
  // Reset DOM
  document.body.innerHTML = '<div id="wizard-root"></div>';
  postMessageCalls = [];

  // Provide acquireVsCodeApi global
  global.acquireVsCodeApi = () => ({
    postMessage: (msg) => postMessageCalls.push(msg),
  });

  // Load wizard.js by evaluating it in the current context
  const scriptPath = path.join(__dirname, "..", "media", "wizard.js");
  const scriptContent = fs.readFileSync(scriptPath, "utf-8");

  // The script uses DOMContentLoaded; since readyState is already "complete"
  // in jsdom, the init() branch that runs immediately will fire.
  eval(scriptContent);
}

function dispatchMessage(data) {
  const event = new MessageEvent("message", { data });
  window.dispatchEvent(event);
}

function clickElement(el) {
  el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
}

function getHarnessCards() {
  return document.querySelectorAll(".harness-card");
}

function getNextButton() {
  const buttons = document.querySelectorAll(".btn-primary");
  for (const btn of buttons) {
    if (btn.textContent === "Next") return btn;
  }
  return null;
}

function getInstallButton() {
  return document.getElementById("install-btn");
}

// ---- Tests ----

describe("Wizard UI", () => {
  beforeEach(() => {
    setupWizard();
    // "ready" should be the first postMessage
    expect(postMessageCalls).toEqual([{ type: "ready" }]);
    postMessageCalls.length = 0;
  });

  test("all five harness cards render in step 1, in documented order", () => {
    const cards = getHarnessCards();
    expect(cards.length).toBe(5);
    const keys = Array.from(cards).map((c) => c.getAttribute("data-harness"));
    expect(keys).toEqual(HARNESS_KEYS);
  });

  test("selecting a card enables Next", () => {
    const nextBtn = getNextButton();
    expect(nextBtn).not.toBeNull();
    expect(nextBtn.disabled).toBe(true);

    const card = getHarnessCards()[0]; // claude-code
    clickElement(card);

    const nextBtnAfter = getNextButton();
    expect(nextBtnAfter.disabled).toBe(false);
  });

  test("step 2 backend toggle: arize shows space_id field, phoenix hides it", () => {
    // Select harness and go to step 2
    clickElement(getHarnessCards()[0]);
    clickElement(getNextButton());

    // Default is arize — space_id should be visible
    const spaceIdField = document.getElementById("field-space_id");
    expect(spaceIdField).not.toBeNull();

    // Switch to phoenix
    const phoenixBtn = document.querySelector('[data-backend="phoenix"]');
    clickElement(phoenixBtn);

    const spaceIdFieldAfter = document.getElementById("field-space_id");
    expect(spaceIdFieldAfter).toBeNull();
  });

  test("step 3 logging toggles default to on", () => {
    // Navigate to step 3
    clickElement(getHarnessCards()[0]);
    clickElement(getNextButton());

    // Fill required fields for arize to enable Next
    setInputValue("field-endpoint", "otlp.arize.com:443");
    setInputValue("field-api_key", "test-key");
    setInputValue("field-space_id", "test-space");
    clickElement(getNextButton());

    // Check logging toggles
    const prompts = document.getElementById("field-log_prompts");
    const toolDetails = document.getElementById("field-log_tool_details");
    const toolContent = document.getElementById("field-log_tool_content");

    expect(prompts).not.toBeNull();
    expect(prompts.checked).toBe(true);
    expect(toolDetails.checked).toBe(true);
    expect(toolContent.checked).toBe(true);
  });

  test("clicking Install emits postMessage with type install and correct request shape", () => {
    // Navigate through all steps
    clickElement(getHarnessCards()[1]); // codex
    clickElement(getNextButton());

    setInputValue("field-endpoint", "otlp.arize.com:443");
    setInputValue("field-api_key", "my-key");
    setInputValue("field-space_id", "my-space");
    clickElement(getNextButton());

    setInputValue("field-project_name", "my-project");
    clickElement(getNextButton());

    // Now on step 4 — click Install
    const installBtn = getInstallButton();
    expect(installBtn).not.toBeNull();
    clickElement(installBtn);

    const installMsg = postMessageCalls.find((m) => m.type === "install");
    expect(installMsg).toBeDefined();
    expect(installMsg.request).toBeDefined();

    const req = installMsg.request;
    // Assert all required keys are present
    expect(req.harness).toBe("codex");
    expect(req.backend).toBeDefined();
    expect(req.backend.target).toBe("arize");
    expect(req.backend.endpoint).toBe("otlp.arize.com:443");
    expect(req.backend.api_key).toBe("my-key");
    expect(req.backend.space_id).toBe("my-space");
    expect(req.project_name).toBe("my-project");
    expect(req).toHaveProperty("user_id");
    expect(req).toHaveProperty("with_skills");
    expect(req).toHaveProperty("logging");
    expect(req.logging).toHaveProperty("prompts");
    expect(req.logging).toHaveProperty("tool_details");
    expect(req.logging).toHaveProperty("tool_content");
  });

  test("receiving log message appends child to #wizard-log with matching class", () => {
    // Navigate to step 4
    clickElement(getHarnessCards()[0]);
    clickElement(getNextButton());

    setInputValue("field-endpoint", "otlp.arize.com:443");
    setInputValue("field-api_key", "k");
    setInputValue("field-space_id", "s");
    clickElement(getNextButton());
    clickElement(getNextButton());

    // Click install to show log area
    clickElement(getInstallButton());

    // Send log messages
    dispatchMessage({ type: "log", level: "info", message: "Starting install..." });
    dispatchMessage({ type: "log", level: "error", message: "Something went wrong" });

    const logEl = document.getElementById("wizard-log");
    expect(logEl).not.toBeNull();

    const children = logEl.querySelectorAll(".log");
    expect(children.length).toBe(2);
    expect(children[0].classList.contains("log-info")).toBe(true);
    expect(children[0].textContent).toBe("Starting install...");
    expect(children[1].classList.contains("log-error")).toBe(true);
    expect(children[1].textContent).toBe("Something went wrong");
  });

  test("receiving result with success shows success state and Close button", () => {
    // Navigate to step 4
    clickElement(getHarnessCards()[0]);
    clickElement(getNextButton());

    setInputValue("field-endpoint", "otlp.arize.com:443");
    setInputValue("field-api_key", "k");
    setInputValue("field-space_id", "s");
    clickElement(getNextButton());
    clickElement(getNextButton());

    clickElement(getInstallButton());

    // Send result
    dispatchMessage({
      type: "result",
      payload: { success: true, error: null, harness: "claude-code", logs: [] },
    });

    // Success banner
    const banner = document.querySelector(".result-banner.success");
    expect(banner).not.toBeNull();

    // Close button
    const closeBtn = Array.from(document.querySelectorAll(".btn-primary")).find(
      (b) => b.textContent === "Close"
    );
    expect(closeBtn).not.toBeNull();

    // Install button should be gone
    expect(getInstallButton()).toBeNull();
  });
});

// ---- Helpers ----

function setInputValue(id, value) {
  const input = document.getElementById(id);
  if (!input) throw new Error("Input #" + id + " not found");
  // Set native value and fire input event
  const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value"
  ).set;
  nativeInputValueSetter.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}
