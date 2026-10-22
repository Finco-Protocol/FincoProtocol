import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const base = (process.env.FINCO_PREVIEW_BASE || "http://127.0.0.1:8081/__mockup/preview/finco-model").replace(/\/$/, "");
const chromePath = process.env.CHROMIUM_PATH || "/repl/tools/bin/chromium";
const evidenceDir = path.resolve("test-evidence");
const cases = [];
const performanceEvidence = [];
const accessibilityEvidence = [];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

class BrowserPage {
  constructor() {
    this.pending = new Map();
    this.nextId = 0;
    this.consoleErrors = [];
      this.previewLifecycleNotes = [];
  }

  async start() {
    this.profile = await mkdtemp(path.join(os.tmpdir(), "finco-browser-"));
    this.browser = spawn(chromePath, [
      "--headless=new",
      "--no-sandbox",
      "--disable-gpu",
      "--disable-dev-shm-usage",
      "--remote-allow-origins=*",
      "--remote-debugging-port=0",
      `--user-data-dir=${this.profile}`,
      "about:blank",
    ], { stdio: "ignore" });

    let port;
    for (let attempt = 0; attempt < 100; attempt += 1) {
      try {
        port = (await readFile(path.join(this.profile, "DevToolsActivePort"), "utf8")).split("\n")[0];
        break;
      } catch {
        await sleep(100);
      }
    }
    if (!port) throw new Error(`Chromium did not expose a DevTools port: ${chromePath}`);

    const response = await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" });
    if (!response.ok) throw new Error(`Could not create Chromium page (HTTP ${response.status})`);
    const target = await response.json();
    this.ws = new WebSocket(target.webSocketDebuggerUrl);
    this.ws.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      const recordBrowserMessage = (text) => {
        if (/WebSocket connection to .*\/__mockup\/\?token=.*failed: Page entered Back-Forward Cache\./.test(text)) {
          this.previewLifecycleNotes.push("Vite preview HMR WebSocket closed when Chromium placed the page in Back-Forward Cache; transient token redacted.");
        } else {
          this.consoleErrors.push(text);
        }
      };
      if (message.method === "Runtime.exceptionThrown") {
        recordBrowserMessage(message.params.exceptionDetails.exception?.description || "Uncaught page exception");
      } else if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") {
        recordBrowserMessage(message.params.args.map((arg) => arg.value || arg.description || "").join(" "));
      } else if (message.method === "Log.entryAdded" && message.params.entry.level === "error") {
        recordBrowserMessage(message.params.entry.text);
      }
      if (message.id && this.pending.has(message.id)) {
        const promise = this.pending.get(message.id);
        this.pending.delete(message.id);
        if (message.error) promise.reject(new Error(message.error.message));
        else promise.resolve(message.result);
      }
    });
    await new Promise((resolve, reject) => {
      this.ws.addEventListener("open", resolve, { once: true });
      this.ws.addEventListener("error", reject, { once: true });
    });
    await this.send("Page.enable");
    await this.send("Runtime.enable");
    await this.send("Log.enable");
    await this.viewport(1440);
  }

  send(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = ++this.nextId;
      const timeout = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`DevTools command timed out: ${method}`));
      }, 10_000);
      this.pending.set(id, {
        resolve: (value) => { clearTimeout(timeout); resolve(value); },
        reject: (error) => { clearTimeout(timeout); reject(error); },
      });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression) {
    const result = await this.send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.exception?.description || "Browser evaluation failed");
    }
    return result.result?.value;
  }

  async viewport(width, height = 900) {
    await this.send("Emulation.setDeviceMetricsOverride", {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await sleep(120);
  }

  async goto(pathname) {
    const url = pathname.startsWith("http") ? pathname : `${base}/${pathname.replace(/^\//, "")}`;
    const expectedPath = new URL(url).pathname;
    await this.send("Page.navigate", { url });
    await this.waitFor(`location.pathname === ${JSON.stringify(expectedPath)} && document.readyState === 'complete' && Boolean(document.querySelector('h1'))`);
  }

  async waitFor(expression, timeoutMs = 8_000) {
    const end = Date.now() + timeoutMs;
    while (Date.now() < end) {
      try {
        if (await this.evaluate(`Boolean(${expression})`)) return;
      } catch {
        // A navigation can temporarily replace the execution context.
      }
      await sleep(80);
    }
    throw new Error(`Timed out waiting for browser condition: ${expression}`);
  }

  async elementBox(expression) {
    return this.evaluate(`(() => {
      const element = ${expression};
      if (!element) return null;
      element.scrollIntoView({ block: "center", inline: "nearest" });
      const rect = element.getBoundingClientRect();
      if (!rect.width || !rect.height) return null;
      return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    })()`);
  }

  async clickExpression(expression) {
    const point = await this.elementBox(expression);
    if (!point) throw new Error(`Clickable element not found: ${expression}`);
    await this.send("Input.dispatchMouseEvent", { type: "mouseMoved", ...point });
    await this.send("Input.dispatchMouseEvent", { type: "mousePressed", ...point, button: "left", clickCount: 1 });
    await this.send("Input.dispatchMouseEvent", { type: "mouseReleased", ...point, button: "left", clickCount: 1 });
    await sleep(120);
  }

  async clickText(text, selector = "button,a,[role=button],[role=tab]", exact = false) {
    const expression = `(() => {
      const wanted = ${JSON.stringify(text)};
      const normalize = (value) => value.replace(/\\s+/g, " ").trim();
      return [...document.querySelectorAll(${JSON.stringify(selector)})].find((element) => {
        const actual = normalize(element.innerText || element.getAttribute("aria-label") || "");
        return element.getClientRects().length && (${exact ? "actual === wanted" : "actual.includes(wanted)"});
      });
    })()`;
    await this.clickExpression(expression);
  }

  async clickId(id) {
    await this.clickExpression(`document.getElementById(${JSON.stringify(id)})`);
  }

  async clickAria(label) {
    await this.clickExpression(`(() => [...document.querySelectorAll("[aria-label]")].find((e) => e.getAttribute("aria-label") === ${JSON.stringify(label)}))()`);
  }

  async wheel(selector, deltaX, deltaY) {
    const point = await this.evaluate(`(() => {
      const element = document.querySelector(${JSON.stringify(selector)});
      if (!element) return null;
      element.scrollIntoView({ block: "center", inline: "nearest" });
      const rect = element.getBoundingClientRect();
      return { x: rect.left + Math.min(rect.width - 4, Math.max(4, rect.width / 2)), y: rect.top + Math.min(rect.height - 4, Math.max(4, rect.height / 2)) };
    })()`);
    if (!point) throw new Error(`Scrollable region not found: ${selector}`);
    await this.send("Input.dispatchMouseEvent", { type: "mouseWheel", ...point, deltaX, deltaY });
    await sleep(180);
  }

  async clickNavHref(fragment) {
    await this.clickExpression(`(() => [...document.querySelectorAll(".fm-wb-tree a")].find((a) => a.getAttribute("href")?.includes(${JSON.stringify(fragment)})))()`);
    await this.waitFor("Boolean(document.querySelector('h1'))");
  }

  async press(key, options = {}) {
    const keyInfo = {
      Enter: ["Enter", 13],
      Tab: ["Tab", 9],
      Escape: ["Escape", 27],
      ArrowDown: ["ArrowDown", 40],
      ArrowUp: ["ArrowUp", 38],
      ArrowLeft: ["ArrowLeft", 37],
      ArrowRight: ["ArrowRight", 39],
      F2: ["F2", 113],
      z: ["KeyZ", 90],
      a: ["KeyA", 65],
      Home: ["Home", 36],
    }[key];
    if (!keyInfo) throw new Error(`Unsupported test key: ${key}`);
    const [code, windowsVirtualKeyCode] = keyInfo;
    const modifiers = (options.ctrl ? 2 : 0) | (options.meta ? 4 : 0) | (options.shift ? 8 : 0);
    const params = { key, code, windowsVirtualKeyCode, modifiers };
    await this.send("Input.dispatchKeyEvent", { type: "keyDown", ...params });
    await this.send("Input.dispatchKeyEvent", { type: "keyUp", ...params });
    await sleep(80);
  }

  async replaceFocusedText(value) {
    await this.press("a", { ctrl: true });
    await this.send("Input.insertText", { text: value });
    await sleep(100);
  }

  async typeIntoAria(label, value) {
    await this.clickExpression(`(() => [...document.querySelectorAll("input,textarea")].find((e) => e.getAttribute("aria-label") === ${JSON.stringify(label)}))()`);
    await this.replaceFocusedText(value);
  }

  async chooseSelect(label, optionText) {
    const index = await this.evaluate(`(() => {
      const normalize = (value) => value.replace(/\\s+/g, " ").trim();
      const select = [...document.querySelectorAll("select")].find((e) => normalize(e.getAttribute("aria-label") || e.labels?.[0]?.innerText || "") === normalize(${JSON.stringify(label)}));
      return select ? [...select.options].findIndex((option) => option.textContent.trim() === ${JSON.stringify(optionText)}) : -1;
    })()`);
    if (index < 0) throw new Error(`Option '${optionText}' not found in select '${label}'`);
    await this.clickExpression(`(() => {
      const normalize = (value) => value.replace(/\\s+/g, " ").trim();
      return [...document.querySelectorAll("select")].find((e) => normalize(e.getAttribute("aria-label") || e.labels?.[0]?.innerText || "") === normalize(${JSON.stringify(label)}));
    })()`);
    await this.press("Home");
    for (let i = 0; i < index; i += 1) await this.press("ArrowDown");
    await this.press("Enter");
  }

  async dispatchPaste(selector, text) {
    return this.evaluate(`(() => {
      const target = document.querySelector(${JSON.stringify(selector)});
      if (!target) return { found: false, prevented: false };
      const data = new DataTransfer();
      data.setData("text/plain", ${JSON.stringify(text)});
      const event = new ClipboardEvent("paste", { bubbles: true, cancelable: true, clipboardData: data });
      target.dispatchEvent(event);
      return { found: true, prevented: event.defaultPrevented };
    })()`);
  }

  async dimensions() {
    return this.evaluate(`({
      viewport: window.innerWidth,
      document: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
      height: window.innerHeight
    })`);
  }

  async screenshot(name) {
    await mkdir(evidenceDir, { recursive: true });
    const result = await this.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    const filename = path.join(evidenceDir, name);
    await writeFile(filename, Buffer.from(result.data, "base64"));
    return filename;
  }

  async close() {
    this.ws?.close();
    if (this.browser && this.browser.exitCode === null) {
      const exited = new Promise((resolve) => this.browser.once("exit", resolve));
      this.browser.kill("SIGTERM");
      await Promise.race([exited, sleep(1500)]);
    }
    if (this.profile) await rm(this.profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  }
}

async function check(name, fn) {
  try {
    const detail = await fn();
    cases.push({ name, status: "PASS", detail: detail ?? "" });
    console.log(`PASS ${name}${detail ? ` — ${detail}` : ""}`);
  } catch (error) {
    cases.push({ name, status: "FAIL", detail: error.message });
    console.error(`FAIL ${name} — ${error.message}`);
  }
}

const page = new BrowserPage();
try {
  await page.start();

  await check("full React root composes the existing three FINCO pages without a new Canvas frame", async () => {
    const compositionUrl = `${new URL(base).origin}/__mockup/?finco-app-composition=1`;
    await page.viewport(1440);
    await page.goto(compositionUrl);
    const startingPath = await page.evaluate("location.pathname");
    assert.ok(await page.evaluate('Boolean(document.querySelector("[data-testid=finco-react-composition]"))'));
    for (const [label, expected] of [
      ["Model Workspace", ".fm-wb-navigation"],
      ["Results & Analysis", ".fm-kpi-grid"],
      ["Project Library", ".fm-table"],
    ]) {
      await page.clickText(label, '[aria-label="FINCO application route proof"] button', true);
      await page.waitFor(`Boolean(document.querySelector(${JSON.stringify(expected)}))`);
      assert.equal(await page.evaluate("location.pathname"), startingPath, "Composition route changed the document instead of swapping the mounted page");
    }
    return "One React root mounted the three existing exported pages in turn; route switching stayed in-page and no Canvas shape was added.";
  });

  await check("I16 separately routed full React entry reuses Library, Workspace and provider-fed Results", async () => {
    const transferRoot = `${new URL(base).origin}/__mockup/finco-transfer/`;
    await page.viewport(1440);
    await page.goto(transferRoot);
    await page.evaluate("sessionStorage.clear()");
    await page.goto(transferRoot);
    await page.waitFor(`Boolean(document.querySelector('[data-testid="finco-transfer-app"][data-route="library"]'))`);
    assert.match(await page.evaluate("document.querySelector('h1')?.innerText || ''"), /Project library/i);
    await page.screenshot("i16-transfer-library-1440.png");
    for (const width of [900, 390]) {
      await page.viewport(width);
      const layout = await page.dimensions();
      assert.ok(layout.document <= width, `Transfer Library overflows document at ${width}px: ${JSON.stringify(layout)}`);
      if (width === 900) await page.screenshot("i16-transfer-library-900.png");
    }
    await page.viewport(1440);
    await page.clickAria("Open reference Adriatic Solar I");
    await page.waitFor(`Boolean(document.querySelector('[data-testid="finco-transfer-app"][data-route="workspace"]'))`);
    await page.waitFor(`document.body.innerText.includes("REFERENCE · READ ONLY")`);
    assert.match(await page.evaluate("location.pathname"), /\/projects\/PRJ-0241\/workbook$/);
    assert.ok(await page.evaluate(`document.body.innerText.includes("REFERENCE · READ ONLY")`));
    assert.equal(await page.evaluate(`(() => [...document.querySelectorAll("button")].find(button => /Save disabled · Reference/.test(button.innerText))?.disabled)()`), true);
    await page.clickText("Create working copy", "button", true);
    await page.waitFor(`location.pathname.includes('/projects/DEMO-WC-') && new URLSearchParams(location.search).get('mode') === 'working-copy'`);
    assert.match(await page.evaluate("document.body.innerText"), /Demo draft · browser session only/i);
    await page.clickId("wb-cell-0-0");
    await page.press("F2");
    await page.replaceFocusedText("121");
    await page.press("Enter");
    await page.clickText("Save scalar batch");
    await page.waitFor("document.body.innerText.includes('DEMO SAVED')");
    const savedValue = await page.evaluate("document.getElementById('wb-cell-0-0')?.innerText.trim()");
    assert.equal(savedValue, "121");
    for (const width of [1440, 900, 390]) {
      await page.viewport(width);
      const layout = await page.dimensions();
      assert.ok(layout.document <= width, `Transfer Workspace overflows document at ${width}px: ${JSON.stringify(layout)}`);
      if (width === 900) await page.screenshot("i16-transfer-workspace-900.png");
      if (width === 390) await page.screenshot("i16-transfer-workspace-390.png");
    }
    await page.viewport(1440);
    await page.clickText("Results", ".fm-nav a");
    await page.waitFor(`Boolean(document.querySelector('[data-testid="finco-transfer-app"][data-route="results"]'))`);
    assert.match(await page.evaluate("location.pathname"), /\/projects\/DEMO-WC-[^/]+\/results$/);
    await page.waitFor(`document.body.innerText.includes("Revenue · transfer fixture")`);
    assert.ok(await page.evaluate(`Boolean(document.querySelector('[data-testid="finco-transfer-app"]'))`));
    for (const width of [1440, 900, 390]) {
      await page.viewport(width);
      const resultsLayout = await page.dimensions();
      assert.ok(resultsLayout.document <= width, `Transfer Results overflows document at ${width}px: ${JSON.stringify(resultsLayout)}`);
      if (width === 1440) await page.screenshot("i16-transfer-results-1440.png");
      if (width === 900) await page.screenshot("i16-transfer-results-900.png");
      if (width === 390) await page.screenshot("i16-transfer-results-390.png");
    }
    await page.evaluate("history.back()");
    await page.waitFor(`document.querySelector('[data-testid="finco-transfer-app"]')?.dataset.route === 'workspace'`);
    assert.match(await page.evaluate("location.pathname"), /\/projects\/DEMO-WC-[^/]+\/workbook$/);
    await page.evaluate("history.forward()");
    await page.waitFor(`document.querySelector('[data-testid="finco-transfer-app"]')?.dataset.route === 'results'`);
    await page.goto(`${transferRoot}unknown-route`);
    await page.waitFor(`document.querySelector('[data-testid="finco-transfer-app"]')?.dataset.route === 'not-found'`);
    assert.match(await page.evaluate("document.body.innerText"), /FINCO demo route unavailable/i);
    await page.evaluate("sessionStorage.clear()");
    await page.goto("ProjectLibrary");
    return `Standalone route proof: Library→Reference→Working Copy→Save→Results; provider-fed statement rendered; Back/Forward restored route; no document overflow at 1440/900/390 on each of Library, Workspace and Results.`;
  });

  await check("three existing FINCO preview routes render", async () => {
    await page.viewport(1440);
    const pages = [
      ["ProjectLibrary", /Project library/i, ".fm-table"],
      ["ModelWorkspace", /Adriatic Solar I/i, ".fm-wb-navigation"],
      ["ResultsAnalysis", /Results & analysis/i, ".fm-kpi-grid"],
    ];
    for (const [route, expected, marker] of pages) {
      await page.goto(route);
      const title = await page.evaluate("document.querySelector('h1')?.innerText || ''");
      assert.match(title, expected);
      assert.ok(await page.evaluate(`Boolean(document.querySelector(${JSON.stringify(marker)}))`), `${route} content marker missing`);
    }
    return "Project Library, Model Workspace and Results & Analysis loaded in Chromium";
  });

  await check("all three preview layouts avoid document-level horizontal overflow", async () => {
    const routes = ["ProjectLibrary", "ModelWorkspace", "ResultsAnalysis"];
    const widths = [1440, 900, 390];
    for (const route of routes) {
      await page.goto(route);
      for (const width of widths) {
        await page.viewport(width);
        const size = await page.dimensions();
        assert.ok(size.document <= size.viewport + 1, `${route} at ${width}px: document ${size.document}px > viewport ${size.viewport}px`);
        if (route === "ProjectLibrary" && width === 1440) await page.screenshot("i16-library-1440.png");
        if (route === "ModelWorkspace" && width === 900) await page.screenshot("i16-workspace-900.png");
        if (route === "ResultsAnalysis" && width === 390) await page.screenshot("i16-results-390.png");
      }
    }
    return "9 route/width checks at 1440, 900 and 390px; saved 3 representative screenshots";
  });

  await check("I13-A reference inspection, isolated working-copy lifecycle and reset", async () => {
    await page.viewport(1440);
    await page.goto("ProjectLibrary");
    assert.match(await page.evaluate("document.body.innerText"), /Portfolio totals and charts remain fixed synthetic reference snapshots/i);
    await page.clickAria("Open reference Adriatic Solar I");
    await page.waitFor("location.pathname.includes('ModelWorkspace') && new URLSearchParams(location.search).get('mode') === 'reference'");
    await page.waitFor("document.body.innerText.includes('REFERENCE · READ ONLY')");
    assert.match(await page.evaluate("document.body.innerText"), /REFERENCE · READ ONLY/);
    assert.equal(await page.evaluate(`(() => [...document.querySelectorAll("button")].find(button => /Save disabled · Reference/.test(button.innerText))?.disabled)()`), true);
    assert.equal(await page.evaluate(`(() => [...document.querySelectorAll("button")].find(button => /Run disabled · Reference/.test(button.innerText))?.disabled)()`), true);
    await page.clickId("wb-cell-0-0");
    await page.press("F2");
    assert.equal(await page.evaluate("Boolean(document.querySelector('.fm-wb-grid-scroll input'))"), false, "Reference cell opened an editor");

    await page.clickText("Create working copy", "button");
    await page.waitFor("location.pathname.includes('ModelWorkspace') && new URLSearchParams(location.search).get('mode') === 'working-copy' && new URLSearchParams(location.search).get('projectId').startsWith('DEMO-WC-')");
    await page.waitFor("/Working copy/i.test(document.querySelector('.fm-shell-header h1')?.innerText || '')");
    const first = await page.evaluate(`({
      id: new URLSearchParams(location.search).get('projectId'),
      name: document.querySelector('.fm-shell-header h1')?.innerText || '',
      parent: document.body.innerText.includes('Adriatic Solar I')
    })`);
    assert.match(first.name, /Adriatic Solar I — Working copy/);
    assert.equal(first.parent, true, "Parent reference context was not carried into the workspace");
    await page.clickId("wb-cell-0-0");
    await page.press("F2");
    await page.replaceFocusedText("121");
    await page.press("Enter");
    assert.equal(await page.evaluate("document.getElementById('wb-cell-0-0')?.innerText.trim()"), "121");
    await page.clickText("Save scalar batch");
    await page.waitFor("document.body.innerText.includes('DEMO SAVED')");
    assert.match(await page.evaluate("document.body.innerText"), /no backend write or Run was triggered|no Run/i);

    await page.goto("ProjectLibrary");
    assert.match(await page.evaluate("document.body.innerText"), /reload preserves this browser-tab session/i);
    await page.evaluate("location.reload()");
    await page.waitFor("Boolean(document.querySelector('.fm-table'))");
    await page.clickAria("Open reference Adriatic Solar I");
    await page.waitFor("new URLSearchParams(location.search).get('mode') === 'reference'");
    assert.equal(await page.evaluate("document.getElementById('wb-cell-0-0')?.innerText.trim()"), "120", "Reference value changed after editing the copy");
    await page.goto("ProjectLibrary");
    await page.clickAria("Create working copy from Adriatic Solar I");
    await page.waitFor("new URLSearchParams(location.search).get('mode') === 'working-copy' && new URLSearchParams(location.search).get('projectId').endsWith('-02')");
    assert.match(await page.evaluate("document.querySelector('.fm-shell-header h1')?.innerText || ''"), /Working copy \(2\)/);
    await page.goto("ProjectLibrary");
    await page.clickAria("Open working copy Adriatic Solar I — Working copy (2)");
    await page.waitFor("new URLSearchParams(location.search).get('projectId').endsWith('-02')");
    assert.equal(await page.evaluate("document.getElementById('wb-cell-0-0')?.innerText.trim()"), "120", "New duplicate inherited another copy's draft instead of its Reference baseline");
    await page.clickId("wb-cell-0-0");
    await page.press("F2");
    await page.replaceFocusedText("123");
    await page.press("Enter");
    await page.clickText("Save scalar batch");
    await page.waitFor("document.body.innerText.includes('DEMO SAVED')");
    await page.goto("ProjectLibrary");
    const firstCopyButton = `Open working copy Adriatic Solar I — Working copy`;
    await page.clickAria(firstCopyButton);
    await page.waitFor(`new URLSearchParams(location.search).get('projectId') === ${JSON.stringify(first.id)}`);
    assert.equal(await page.evaluate("document.getElementById('wb-cell-0-0')?.innerText.trim()"), "121", "Reopened copy did not restore its local Save");

    await page.evaluate("window.confirm = () => true");
    await page.clickText("Reset local demo session", "button", true);
    await page.waitFor("document.body.innerText.includes('unavailable in the current browser-tab session') || location.pathname.includes('ModelWorkspace')");
    await page.goto("ProjectLibrary");
    assert.equal(await page.evaluate("document.querySelectorAll('button[aria-label^=\"Open working copy\"]').length"), 0, "Reset retained a session-only copy");
    return "Read-only Reference blocked edits/Save/Run; two uniquely named copies created; one copy's Save remained isolated, survived reload, reopened correctly, and reset removed the session registry.";
  });

  await check("I15-W4 two-copy isolation across all PPA and facility drafts", async () => {
    await page.viewport(1440);
    await page.evaluate("sessionStorage.clear()");
    const referenceUrl = sheet => `ModelWorkspace?projectId=PRJ-0241&mode=reference&sheet=${sheet}`;
    const copyUrl = (projectId, sheet) => `ModelWorkspace?projectId=${projectId}&mode=working-copy&sheet=${sheet}`;
    const visitRecord = async (projectId, mode, sheet, id, marker) => {
      const recordKey = sheet === "revenue" ? "contract" : "facility";
      const baseUrl = mode === "reference" ? referenceUrl(sheet) : copyUrl(projectId, sheet);
      await page.goto(`${baseUrl}&${recordKey}=${encodeURIComponent(id)}`);
      await page.waitFor(`Boolean(document.querySelector(${JSON.stringify(marker)})) && new URLSearchParams(location.search).get(${JSON.stringify(recordKey)}) === ${JSON.stringify(id)}`);
      await sleep(150);
      const selection = await page.evaluate(`(() => ({
        url:location.href,
        selected:[...document.querySelectorAll(".fm-wf-table tbody .fm-wf-row-button")].filter(button => button.getAttribute("aria-pressed") === "true").map(button => button.innerText.trim()),
        options:[...document.querySelectorAll(".fm-wf-table tbody .fm-wf-row-button")].map(button => ({text:button.innerText.trim(),pressed:button.getAttribute("aria-pressed"),disabled:button.disabled}))
      }))()`);
      assert.ok(selection.selected.includes(id), `Route did not select ${id}: ${JSON.stringify(selection)}`);
    };
    const visitReferenceSheet = async (sheet, storageKey, marker) => {
      await page.goto(referenceUrl(sheet));
      await page.waitFor(`Boolean(document.querySelector(${JSON.stringify(marker)}))`);
      await page.waitFor(`Object.keys(sessionStorage).some(key => key.endsWith(${JSON.stringify(storageKey)}))`);
    };
    const visitCopySheet = async (projectId, sheet, marker) => {
      await page.goto(copyUrl(projectId, sheet));
      await page.waitFor(`new URLSearchParams(location.search).get('projectId') === ${JSON.stringify(projectId)}`);
      await page.waitFor(`Boolean(document.querySelector(${JSON.stringify(marker)}))`);
    };
    const firstFieldValue = async () => page.evaluate(`(() => [...document.querySelectorAll(".fm-wf-fields input")]
      .find(input => input.getClientRects().length && input.value)?.value || "")()`);
    const replaceFirstField = async value => {
      const focused = await page.evaluate(`(() => {
        const input = [...document.querySelectorAll(".fm-wf-fields input")]
          .find(item => item.getClientRects().length && !item.disabled && item.value);
        input?.focus();
        return Boolean(input);
      })()`);
      assert.equal(focused, true, "Expected an editable module field");
      await page.replaceFocusedText(value);
    };
    const periodCell = async () => page.evaluate(`(() => {
      const button = [...document.querySelectorAll(".fm-period-table tbody button.fm-period-cell-button:not(:disabled)")]
        .find(item => item.getClientRects().length && item.innerText.trim() && item.innerText.trim() !== "—");
      return button ? { label: button.getAttribute("aria-label"), value: button.innerText.trim() } : null;
    })()`);
    const firstReferencePeriodValue = async () => page.evaluate(`(() => {
      const cell = [...document.querySelectorAll(".fm-period-table tbody td button.fm-period-cell-button")]
        .find(button => button.innerText.trim() && button.innerText.trim() !== "—" && Number.isFinite(Number(button.innerText.trim())));
      return cell ? { value: cell.innerText.trim(), label: cell.getAttribute("aria-label") || "" } : null;
    })()`);
    const editAndSavePeriod = async nextValue => {
      const cell = await periodCell();
      assert.ok(cell, "Expected an editable synthetic cost period");
      await page.clickAria(cell.label);
      await page.press("Enter");
      await page.replaceFocusedText(nextValue);
      await page.press("Enter");
      await page.waitFor("document.querySelector('.fm-period-state')?.innerText.includes('UNSAVED')");
      await page.clickId("finco-line-save");
      await page.waitFor("document.querySelector('.fm-period-state')?.innerText.includes('LOCAL DEMO SAVE')");
      assert.match(await page.evaluate("document.querySelector('.fm-period-state')?.innerText || ''"), /LOCAL DEMO SAVE · NOT RUN/i);
      return { ...cell, nextValue };
    };
    const readPeriodCell = async () => (await periodCell())?.value || "";
    const ppaIds = ["PPA-A", "PPA-B", "PPA-C"];
    const facilityIds = ["Senior Debt A", "Senior Debt B", "Junior / Mezzanine", "Shareholder Loan (SHL)", "Sponsor Equity"];
    const saveRecord = async (label, value) => {
      await replaceFirstField(value);
      await page.clickText(`Save ${label} demo`, ".fm-wf-actions button");
      await page.waitFor('document.querySelector(".fm-wf-editor-head > span")?.innerText.includes("LOCAL SAVE")');
      return await firstFieldValue();
    };

    const referencePpaValues = {};
    for (const id of ppaIds) {
      await visitRecord("PRJ-0241", "reference", "revenue", id, '[aria-label="Synthetic multi-contract PPA editor"]');
      referencePpaValues[id] = await firstFieldValue();
    }
    const referenceFacilityValues = {};
    for (const id of facilityIds) {
      await visitRecord("PRJ-0241", "reference", "senior-debt", id, '[aria-label="Synthetic financing and capital structure"]');
      referenceFacilityValues[id] = await firstFieldValue();
    }
    await visitReferenceSheet("scenarios", "scenario-drafts", '[aria-label="Synthetic scenario editor"]');
    const referenceScenario = await page.evaluate('document.querySelector("[aria-label=\\"Scenario power price delta\\"]")?.value || ""');
    await visitReferenceSheet("capex", "cost-line-draft", ".fm-period-scroll");
    const referenceCapex = await firstReferencePeriodValue();
    await visitReferenceSheet("opex", "cost-line-draft", ".fm-period-scroll");
    const referenceOpex = await firstReferencePeriodValue();
    assert.ok(Object.values(referencePpaValues).every(Boolean) && Object.values(referenceFacilityValues).every(Boolean) && referenceScenario !== "" && referenceCapex && referenceOpex);

    await page.goto(referenceUrl("input-grid"));
    await page.clickText("Create working copy", "button");
    await page.waitFor("new URLSearchParams(location.search).get('mode') === 'working-copy' && new URLSearchParams(location.search).get('projectId').startsWith('DEMO-WC-')");
    await page.waitFor("Boolean(document.getElementById('wb-cell-0-0'))");
    const copyA = await page.evaluate("new URLSearchParams(location.search).get('projectId')");
    await page.clickId("wb-cell-0-0");
    await page.press("F2");
    await page.replaceFocusedText("121");
    await page.press("Enter");
    await page.clickText("Save scalar batch");
    await page.waitFor("document.body.innerText.includes('DEMO SAVED')");

    await visitCopySheet(copyA, "revenue", '[aria-label="Synthetic multi-contract PPA editor"]');
    await replaceFirstField("Copy A PPA-A");
    await page.clickText("Save PPA-A demo", ".fm-wf-actions button");
    await page.waitFor('document.querySelector("[aria-label=\\"Synthetic multi-contract PPA editor\\"] .fm-wf-editor-head > span")?.innerText.includes("LOCAL SAVE")');
    const copyAPpaValues = { "PPA-A": await firstFieldValue() };
    for (const id of ["PPA-B", "PPA-C"]) {
      await visitRecord(copyA, "working-copy", "revenue", id, '[aria-label="Synthetic multi-contract PPA editor"]');
      copyAPpaValues[id] = await saveRecord(id, `Copy A ${id}`);
    }
    await visitCopySheet(copyA, "senior-debt", '[aria-label="Synthetic financing and capital structure"]');
    await replaceFirstField("Copy A Senior A");
    await page.clickText("Save Senior Debt A demo", ".fm-wf-actions button");
    await page.waitFor('document.querySelector("[aria-label=\\"Synthetic financing and capital structure\\"] .fm-wf-editor-head > span")?.innerText.includes("LOCAL SAVE")');
    const copyAFacilityValues = { "Senior Debt A": await firstFieldValue() };
    for (const id of facilityIds.slice(1)) {
      await visitRecord(copyA, "working-copy", "senior-debt", id, '[aria-label="Synthetic financing and capital structure"]');
      copyAFacilityValues[id] = await saveRecord(id, `Copy A ${id}`);
    }
    await visitCopySheet(copyA, "scenarios", '[aria-label="Synthetic scenario editor"]');
    await page.typeIntoAria("Scenario power price delta", "-7");
    await page.clickText("Save Base case demo", ".fm-wf-actions button");
    await page.waitFor("document.body.innerText.includes('Fixed results were not recalculated')");
    const copyAScenario = await page.evaluate(`document.querySelector('[aria-label="Scenario power price delta"]')?.value || ""`);
    await visitCopySheet(copyA, "capex", ".fm-period-scroll");
    const copyACapex = await editAndSavePeriod(String(Number(referenceCapex.value) + 0.1));
    await visitCopySheet(copyA, "opex", ".fm-period-scroll");
    const copyAOpex = await editAndSavePeriod(String(Number(referenceOpex.value) + 0.1));

    await page.goto("ProjectLibrary");
    await page.clickAria("Create working copy from Adriatic Solar I");
    await page.waitFor("new URLSearchParams(location.search).get('mode') === 'working-copy' && new URLSearchParams(location.search).get('projectId').endsWith('-02')");
    const copyB = await page.evaluate("new URLSearchParams(location.search).get('projectId')");
    assert.notEqual(copyA, copyB);
    await page.clickId("wb-cell-0-0");
    await page.press("F2");
    await page.replaceFocusedText("124");
    await page.press("Enter");
    await page.waitFor("document.getElementById('wb-cell-0-0')?.innerText.trim() === '124'");
    await page.waitFor("document.body.innerText.includes('UNSAVED')");
    assert.equal(await page.evaluate("document.getElementById('wb-cell-0-0')?.innerText.trim()"), "124");
    await page.clickText("Save scalar batch");
    await page.waitFor("document.body.innerText.includes('DEMO SAVED')");

    await visitCopySheet(copyB, "revenue", '[aria-label="Synthetic multi-contract PPA editor"]');
    for (const id of ppaIds) {
      await visitRecord(copyB, "working-copy", "revenue", id, '[aria-label="Synthetic multi-contract PPA editor"]');
      assert.equal(await firstFieldValue(), referencePpaValues[id], `Copy B inherited Copy A's ${id} draft`);
      if (id === "PPA-A") {
        await replaceFirstField("Copy B PPA-A");
        await page.clickText("Save PPA-A demo", ".fm-wf-actions button");
      } else {
        await saveRecord(id, `Copy B ${id}`);
      }
    }
    await visitCopySheet(copyB, "senior-debt", '[aria-label="Synthetic financing and capital structure"]');
    for (const id of facilityIds) {
      await visitRecord(copyB, "working-copy", "senior-debt", id, '[aria-label="Synthetic financing and capital structure"]');
      assert.equal(await firstFieldValue(), referenceFacilityValues[id], `Copy B inherited Copy A's ${id} draft`);
      await saveRecord(id, `Copy B ${id}`);
    }
    await visitCopySheet(copyB, "scenarios", '[aria-label="Synthetic scenario editor"]');
    assert.equal(await page.evaluate(`document.querySelector('[aria-label="Scenario power price delta"]')?.value || ""`), referenceScenario, "Copy B inherited Copy A's scenario draft");
    await page.typeIntoAria("Scenario power price delta", "12");
    await page.clickText("Save Base case demo", ".fm-wf-actions button");
    await visitCopySheet(copyB, "capex", ".fm-period-scroll");
    assert.equal(await readPeriodCell(), referenceCapex.value, "Copy B inherited Copy A's CAPEX period draft");
    const copyBCapex = await editAndSavePeriod(String(Number(referenceCapex.value) + 0.2));
    await visitCopySheet(copyB, "opex", ".fm-period-scroll");
    assert.equal(await readPeriodCell(), referenceOpex.value, "Copy B inherited Copy A's OPEX period draft");
    const copyBOpex = await editAndSavePeriod(String(Number(referenceOpex.value) + 0.2));

    await page.goto("ProjectLibrary");
    await page.evaluate("location.reload()");
    await page.waitFor("Boolean(document.querySelector('.fm-table'))");
    await page.clickAria("Open working copy Adriatic Solar I — Working copy");
    await page.waitFor(`new URLSearchParams(location.search).get('projectId') === ${JSON.stringify(copyA)}`);
    await page.clickNavHref("sheet=input-grid");
    await page.waitFor("Boolean(document.getElementById('wb-cell-0-0'))");
    assert.equal(await page.evaluate("document.getElementById('wb-cell-0-0')?.innerText.trim()"), "121");
    await visitCopySheet(copyA, "revenue", '[aria-label="Synthetic multi-contract PPA editor"]');
    for (const id of ppaIds) {
      await visitRecord(copyA, "working-copy", "revenue", id, '[aria-label="Synthetic multi-contract PPA editor"]');
      assert.equal(await firstFieldValue(), copyAPpaValues[id], `Copy B or same-tab reload changed Copy A's ${id} record`);
    }
    await visitCopySheet(copyA, "senior-debt", '[aria-label="Synthetic financing and capital structure"]');
    for (const id of facilityIds) {
      await visitRecord(copyA, "working-copy", "senior-debt", id, '[aria-label="Synthetic financing and capital structure"]');
      assert.equal(await firstFieldValue(), copyAFacilityValues[id], `Copy B changed Copy A's ${id} record`);
    }
    await visitCopySheet(copyA, "scenarios", '[aria-label="Synthetic scenario editor"]');
    assert.equal(await page.evaluate(`document.querySelector('[aria-label="Scenario power price delta"]')?.value || ""`), copyAScenario);
    await visitCopySheet(copyA, "capex", ".fm-period-scroll");
    assert.ok(Math.abs(Number(await readPeriodCell()) - Number(copyACapex.nextValue)) < 1e-8);
    await visitCopySheet(copyA, "opex", ".fm-period-scroll");
    assert.ok(Math.abs(Number(await readPeriodCell()) - Number(copyAOpex.nextValue)) < 1e-8);

    await page.evaluate("sessionStorage.clear()");
    await page.goto("ProjectLibrary");
    return `Two independent session-only copies (A=${copyA}, B=${copyB}); Reference stayed the baseline. Browser checked separate scalar, PPA-A/B/C, Senior A/B, Junior, SHL, Equity, Base scenario, CAPEX and OPEX drafts across copy switching; Copy A values survived same-tab reload. Fixed financial outputs remained shared synthetic references.`;
  });

  await check("I15-W5 390px Reference → Working Copy → mobile workbook → statement trace", async () => {
    await page.viewport(390);
    await page.evaluate("sessionStorage.clear()");
    await page.goto("ProjectLibrary");
    const librarySize = await page.dimensions();
    assert.ok(librarySize.document <= 391, `390px Library has page-level horizontal overflow: ${JSON.stringify(librarySize)}`);
    await page.clickAria("Open reference Adriatic Solar I");
    await page.waitFor("new URLSearchParams(location.search).get('mode') === 'reference'");
    await page.waitFor("document.body.innerText.includes('REFERENCE · READ ONLY')");
    const referenceActions = await page.evaluate(`(() => {
      const button = [...document.querySelectorAll("button")].find(item => item.innerText.includes("Create working copy"));
      const picker = document.querySelector(".fm-wb-mobile-picker");
      return {
        createVisible: Boolean(button?.getClientRects().length),
        createDisabled: button?.disabled ?? null,
        mobilePickerDisplay: picker ? getComputedStyle(picker).display : "missing",
        viewport: innerWidth,
        document: document.documentElement.scrollWidth
      };
    })()`);
    assert.equal(referenceActions.createVisible, true);
    assert.equal(referenceActions.createDisabled, false);
    assert.notEqual(referenceActions.mobilePickerDisplay, "none", "Mobile workbook sheet selector is not exposed");
    assert.ok(referenceActions.document <= referenceActions.viewport + 1, `Reference workspace overflows: ${JSON.stringify(referenceActions)}`);
    await page.clickText("Create working copy", "button");
    await page.waitFor("new URLSearchParams(location.search).get('mode') === 'working-copy'");
    const copyId = await page.evaluate("new URLSearchParams(location.search).get('projectId')");
    await page.screenshot("i16-reference-copy-390.png");

    const optionFor = async id => page.evaluate(`([...document.querySelector(".fm-wb-mobile-picker select").options].find(option => option.value === ${JSON.stringify(id)})?.text || "")`);
    const chooseSheet = async id => {
      const option = await optionFor(id);
      assert.ok(option, `Mobile workbook selector is missing ${id}`);
      await page.chooseSelect("Workbook sheet", option);
    };
    await chooseSheet("revenue");
    await page.waitFor("Boolean(document.querySelector('[aria-label=\"Synthetic multi-contract PPA editor\"]'))");
    await page.clickText("PPA-B", "button");
    assert.equal(await page.evaluate("document.querySelector('[aria-label=\"Synthetic multi-contract PPA editor\"] .fm-wf-editor-head h3')?.innerText.includes('PPA-B')"), true);

    await chooseSheet("capex");
    await page.waitFor("Boolean(document.querySelector('.fm-period-scroll'))");
    await page.clickAria("Scroll periods right");
    const capexLayout = await page.evaluate(`(() => {
      const grid = document.querySelector(".fm-period-scroll");
      const metric = grid?.querySelector(".fm-period-metric");
      const action = document.getElementById("finco-line-save");
      const actionRect = action?.getBoundingClientRect();
      return {
        viewport: innerWidth,
        document: document.documentElement.scrollWidth,
        gridScrollsInternally: Boolean(grid && grid.scrollWidth > grid.clientWidth && grid.scrollLeft > 0),
        metricSticky: getComputedStyle(metric || document.body).position,
        actionVisible: Boolean(actionRect && actionRect.width && actionRect.right > 0 && actionRect.left < innerWidth),
        actionWithinViewport: Boolean(actionRect && actionRect.right <= innerWidth + 1),
      };
    })()`);
    assert.ok(capexLayout.document <= capexLayout.viewport + 1, `CAPEX created page-level overflow at 390px: ${JSON.stringify(capexLayout)}`);
    assert.equal(capexLayout.gridScrollsInternally, true);
    assert.equal(capexLayout.metricSticky, "sticky");
    assert.equal(capexLayout.actionVisible, true);
    assert.equal(capexLayout.actionWithinViewport, true, "CAPEX Save action is clipped at 390px");

    await chooseSheet("cfads");
    await page.waitFor("Boolean(document.querySelector('.fm-sw-region'))");
    const resultSize = await page.dimensions();
    assert.ok(resultSize.document <= 391, `390px Results has page-level horizontal overflow: ${JSON.stringify(resultSize)}`);
    const statementRegion = await page.evaluate(`(() => {
      const region = document.querySelector(".fm-sw-region");
      return { scrollWidth: region?.scrollWidth || 0, clientWidth: region?.clientWidth || 0, overflowX: getComputedStyle(region || document.body).overflowX };
    })()`);
    assert.ok(statementRegion.scrollWidth > statementRegion.clientWidth, "Long statement did not keep scrolling inside its own region");
    await page.screenshot("i16-mobile-statement-390.png");
    await page.clickExpression('document.querySelector("button[aria-label*=\\"Open synthetic source trace\\"]")');
    await page.waitFor("document.body.innerText.includes('SYNTHETIC SOURCE TRACE')");
    await page.clickExpression('document.querySelector("a.fm-sw-trace-open")');
    await page.waitFor("location.pathname.includes('ModelWorkspace') && Boolean(document.querySelector('.fm-trace-return'))");
    const traceWorkspace = await page.dimensions();
    assert.ok(traceWorkspace.document <= 391, `Trace workspace overflows at 390px: ${JSON.stringify(traceWorkspace)}`);
    await page.clickText("Return to the selected statement trace", "a");
    await page.waitFor("location.pathname.includes('ResultsAnalysis') && Boolean(document.querySelector('.fm-sw-region'))");
    assert.equal(await page.evaluate("new URLSearchParams(location.search).get('projectId')"), copyId, "Trace return lost the selected copy identity");
    assert.ok((await page.dimensions()).document <= 391, "Statement return created page-level overflow at 390px");
    return `390px real clicks: Library → protected Reference → session-only copy ${copyId} → mobile workbook picker → PPA-B → CAPEX internal scroll/sticky metric/visible Save → CFADS → source trace → return. Document width stayed within the viewport.`;
  });

  await check("I15-W5 accessible names and focus recovery smoke checks", async () => {
    const routeChecks = [];
    for (const route of ["ProjectLibrary", "ModelWorkspace", "ResultsAnalysis"]) {
      await page.viewport(1440);
      await page.goto(route);
      const result = await page.evaluate(`(() => {
        const visible = element => {
          const style = getComputedStyle(element);
          return Boolean(element.getClientRects().length) && style.visibility !== "hidden" && style.display !== "none";
        };
        const controls = [...document.querySelectorAll("button,a,input,select,textarea,[role=button],[role=tab]")]
          .filter(element => visible(element) && !["hidden"].includes(element.type));
        const accessibleName = element => {
          const labelledBy = element.getAttribute("aria-labelledby");
          const referenced = labelledBy ? labelledBy.split(/\\s+/).map(id => document.getElementById(id)?.innerText || "").join(" ") : "";
          const labels = element.labels ? [...element.labels].map(label => label.innerText).join(" ") : "";
          return (element.getAttribute("aria-label") || referenced || labels || element.innerText || element.value || element.title || "").trim();
        };
        return {
          mainCount: document.querySelectorAll("main").length,
          navigationCount: document.querySelectorAll("nav").length,
          navigationValid: document.querySelectorAll("nav").length > 0 &&
            [...document.querySelectorAll("nav")].every(nav => nav.getAttribute("aria-label") || nav.getAttribute("aria-labelledby")),
          controlCount: controls.length,
          unnamed: controls.filter(element => !accessibleName(element)).map(element => ({
            tag: element.tagName,
            role: element.getAttribute("role"),
            type: element.type || "",
            className: String(element.className || "").slice(0, 70)
          }))
        };
      })()`);
      assert.equal(result.mainCount, 1, `${route} should expose one main landmark`);
      assert.ok(result.navigationCount > 0, `${route} should expose at least one navigation landmark`);
      assert.equal(result.navigationValid, true, `${route} has an unnamed navigation landmark`);
      assert.ok(result.controlCount > 0, `${route} has no visible interactive controls`);
      assert.deepEqual(result.unnamed, [], `${route} has visible controls without a computed accessible name`);
      routeChecks.push({ route, controls: result.controlCount, main: result.mainCount, namedNavigationLandmarks: result.navigationCount });
    }

    await page.goto("ModelWorkspace");
    await page.clickNavHref("sheet=capex");
    await page.waitFor("Boolean(document.querySelector('.fm-period-scroll'))");
    const selected = await page.evaluate('Boolean(document.querySelector(".fm-period-table tbody button[tabindex=\\"0\\"]"))');
    assert.equal(selected, true, "No keyboard-selected period cell");
    await page.evaluate('document.querySelector(".fm-period-table tbody button[tabindex=\\"0\\"]")?.focus()');
    await page.press("F2");
    assert.equal(await page.evaluate("Boolean(document.querySelector('.fm-period-input[aria-label]'))"), true, "F2 did not open the focused selected cell");
    await page.press("Escape");
    await page.waitFor('document.activeElement?.classList.contains("fm-period-cell-button")');
    const focusRestored = await page.evaluate('document.activeElement?.classList.contains("fm-period-cell-button") || false');
    assert.equal(focusRestored, true, "Esc did not return focus to the edited grid cell");
    accessibilityEvidence.push({ method: "DOM accessible-name/landmark scan plus real keyboard edit/cancel focus test; not a WCAG or screen-reader audit", routes: routeChecks, focusRestored });
    return `Accessible-name and landmark scan on three live routes (${routeChecks.map(item => `${item.route}:${item.controls}`).join(", ")} visible controls); real F2→Esc returned focus to the grid cell. Full screen-reader/WCAG audit remains untested.`;
  });

  await check("Library search, technology filter, add-local-demo and project identity", async () => {
    await page.viewport(1440);
    await page.goto("ProjectLibrary");
    const before = await page.evaluate("document.querySelectorAll('tbody tr').length");
    assert.ok(before >= 3, `Expected sample projects, found ${before}`);
    await page.typeIntoAria("Search projects", "wind");
    const searched = await page.evaluate("document.querySelectorAll('tbody tr').length");
    assert.ok(searched >= 1 && searched < before, `Search did not narrow rows (${before} -> ${searched})`);
    await page.clickText("Reset filters");
    await page.chooseSelect("Filter technology", "Onshore wind");
    const filtered = await page.evaluate("document.querySelectorAll('tbody tr').length");
    assert.ok(filtered >= 1, "Technology filter returned no projects");
    const project = await page.evaluate(`(() => {
      const button = [...document.querySelectorAll("button")].find((item) => /Open reference North Ridge Wind/.test(item.getAttribute("aria-label") || ""));
      const row = button?.closest("tr");
      return { name: row?.innerText?.trim() || "", label: button?.getAttribute("aria-label") || "" };
    })()`);
    assert.ok(project?.label, "No sample project reference action found");
    await page.clickAria("Open reference North Ridge Wind");
    await page.waitFor("location.pathname.includes('ModelWorkspace')");
    await page.waitFor("Boolean(document.querySelector('.fm-wb-layout'))");
    const identity = await page.evaluate(`({
      heading: document.querySelector(".fm-shell-header h1")?.innerText || document.querySelector("h1")?.innerText || "",
      subtitle: document.querySelector(".fm-subtitle")?.innerText || ""
    })`);
    assert.ok(identity.heading.trim(), `Workspace project name is missing at ${await page.evaluate("location.href")}: ${JSON.stringify(identity)}`);
    assert.match(identity.subtitle, /Onshore wind/i, "Selected technology was not carried into workspace");
    assert.match(await page.evaluate("document.body.innerText"), /REFERENCE · READ ONLY/);
    await page.goto("ProjectLibrary");
    await page.clickText("+ Create project");
    assert.equal(await page.evaluate("document.querySelector('button.fm-btn-primary')?.innerText || ''"), "Demo project added");
    assert.match(await page.evaluate("document.body.innerText"), /New solar project/);
    return `search narrowed ${before} to ${searched}; opened a filtered wind reference read-only and added a local demo project`;
  });

  await check("Input Grid keyboard editing, error recovery, atomic TSV, Save/Run separation", async () => {
    await page.viewport(1440);
    await page.goto("ModelWorkspace");
    await page.clickId("wb-cell-0-0");
    await page.press("F2");
    await page.replaceFocusedText("0");
    await page.press("Enter");
    await page.waitFor("Boolean(document.querySelector('[role=alert]'))");
    assert.match(await page.evaluate("document.querySelector('[role=alert]')?.innerText || ''"), /Demo Save and Run unavailable/i);
    await page.clickText("Save scalar batch");
    await page.clickText("Run demo separately");
    assert.match(await page.evaluate("location.pathname"), /ModelWorkspace/);
    await page.clickId("wb-cell-0-0");
    await page.press("F2");
    await page.replaceFocusedText("120");
    await page.press("Enter");
    await page.waitFor("!document.querySelector('[role=alert]')");

    await page.clickId("wb-cell-0-0");
    await page.press("F2");
    await page.replaceFocusedText("121");
    await page.press("Escape");
    assert.equal(await page.evaluate("document.getElementById('wb-cell-0-0')?.innerText.trim()"), "120");

    await page.clickId("wb-cell-0-0");
    await page.press("F2");
    await page.replaceFocusedText("121");
    await page.press("Enter");
    await page.press("z", { ctrl: true });
    assert.equal(await page.evaluate("document.getElementById('wb-cell-0-0')?.innerText.trim()"), "120");

    await page.clickId("wb-cell-0-0");
    await page.press("Tab");
    assert.equal(await page.evaluate("document.activeElement?.id"), "wb-cell-0-1");
    await page.press("Tab", { shift: true });
    assert.equal(await page.evaluate("document.activeElement?.id"), "wb-cell-0-0");
    await page.press("ArrowDown");
    assert.equal(await page.evaluate("document.activeElement?.id"), "wb-cell-1-0");
    const constructionDate = await page.evaluate("document.getElementById('wb-cell-1-0')?.innerText.trim() || ''");
    await page.press("F2");
    await page.replaceFocusedText(constructionDate);
    await page.press("Enter", { shift: true });
    assert.equal(await page.evaluate("document.activeElement?.id"), "wb-cell-0-0", "Shift+Enter did not move to the prior row");

    await page.clickId("wb-cell-0-0");
    const before = await page.evaluate(`({
      capacity: document.getElementById("wb-cell-0-0")?.innerText.trim(),
      construction: document.getElementById("wb-cell-1-0")?.innerText.trim()
    })`);
    const validPaste = await page.dispatchPaste("#wb-cell-0-0", "121\n2025-10-01");
    assert.equal(validPaste.found, true);
    assert.equal(validPaste.prevented, true, "Input Grid paste handler did not intercept the test clipboard event");
    await page.waitFor("document.getElementById('wb-cell-0-0')?.innerText.trim() === '121'");
    const afterValid = await page.evaluate(`({
      capacity: document.getElementById("wb-cell-0-0")?.innerText.trim(),
      construction: document.getElementById("wb-cell-1-0")?.innerText.trim()
    })`);
    assert.equal(afterValid.construction, before.construction);
    await page.clickText("Run demo separately");
    assert.match(await page.evaluate("location.pathname"), /ModelWorkspace/, "Run navigated away with an uncommitted draft");
    await page.dispatchPaste("#wb-cell-0-0", "122\nnot-a-date");
    await page.waitFor("Boolean(document.querySelector('[role=status]'))");
    const afterInvalid = await page.evaluate(`({
      capacity: document.getElementById("wb-cell-0-0")?.innerText.trim(),
      construction: document.getElementById("wb-cell-1-0")?.innerText.trim()
    })`);
    assert.deepEqual(afterInvalid, afterValid, "Invalid TSV partially changed the draft");
    await page.clickText("Save scalar batch");
    assert.match(await page.evaluate("document.body.innerText"), /DEMO SAVED|Demo acknowledged/i);
    assert.equal(await page.evaluate("document.activeElement?.tagName"), "BUTTON", "Save did not leave keyboard focus on a control");
    assert.match(await page.evaluate("location.pathname"), /ModelWorkspace/);
    await page.clickText("Run demo separately");
    await page.waitFor("location.pathname.includes('ResultsAnalysis')");
    await page.waitFor("Boolean(document.querySelector('.fm-kpi-grid'))");
    assert.match(await page.evaluate("document.body.innerText"), /7\.82%/);
    await page.goto("ModelWorkspace?projectId=PRJ-0236&project=North%20Ridge%20Wind&technology=Onshore%20wind");
    await page.waitFor("Boolean(document.querySelector('.fm-wb-grid-panel'))");
    assert.match(await page.evaluate("document.querySelector('.fm-shell-header h1')?.innerText || ''"), /North Ridge Wind/);
    assert.match(await page.evaluate("document.body.innerText"), /Shared demo assumptions/i);
    assert.equal(await page.evaluate("document.getElementById('wb-cell-0-0')?.innerText.trim()"), "120");
    await page.clickId("wb-cell-0-0");
    await page.press("F2");
    await page.replaceFocusedText("86");
    await page.press("Enter");
    await page.goto("ModelWorkspace?projectId=PRJ-0241&project=Adriatic%20Solar%20I&technology=Solar%20PV");
    await page.waitFor("Boolean(document.querySelector('.fm-wb-grid-panel'))");
    assert.equal(await page.evaluate("document.getElementById('wb-cell-0-0')?.innerText.trim()"), "121", "Editing Wind changed the existing Solar project draft");
    await page.goto("ModelWorkspace?projectId=PRJ-0236&project=North%20Ridge%20Wind&technology=Onshore%20wind");
    await page.waitFor("Boolean(document.querySelector('.fm-wb-grid-panel'))");
    assert.equal(await page.evaluate("document.getElementById('wb-cell-0-0')?.innerText.trim()"), "86", "Wind working draft was not restored to its project scope");
    return "F2/Enter/Shift+Enter/Esc/arrows/Tab/Shift+Tab/Ctrl+Z; atomic valid/invalid TSV; dirty Run blocked; Save != fixed Run; Wind/Solar draft values 86/121 remain separately scoped";
  });

  await check("CAPEX 18-month / OPEX 12-quarter and 6-half-year planner interaction", async () => {
    await page.viewport(1440);
    await page.goto("ModelWorkspace");
    await page.clickNavHref("sheet=capex");
    await page.waitFor("Boolean(document.querySelector('.fm-period-scroll'))");
    const capexPeriods = await page.evaluate("document.querySelectorAll('.fm-period-table thead .fm-period-heading').length");
    assert.equal(capexPeriods, 18, "CAPEX should expose 18 monthly periods");
    const planner = await page.evaluate(`(() => {
      const scroller = document.querySelector(".fm-period-scroll");
      const table = scroller?.querySelector("table");
      return { scrollWidth: scroller?.scrollWidth || 0, clientWidth: scroller?.clientWidth || 0, className: scroller?.className || "", columns: table?.querySelectorAll("thead th").length || 0 };
    })()`);
    assert.ok(planner.scrollWidth > planner.clientWidth, "Expected the long CAPEX grid to scroll inside its table region");
    const firstCell = await page.evaluate("document.querySelector('.fm-period-table tbody button[aria-label]')?.getAttribute('aria-label') || ''");
    assert.ok(firstCell, "CAPEX period cells need accessible labels");
    const capexEditInfo = await page.evaluate(`(() => {
      const buttons = [...document.querySelectorAll(".fm-period-table tbody button.fm-period-cell-button:not(:disabled)")];
      const button = buttons.find(e => e.getClientRects().length && e.innerText.trim() && e.innerText.trim() !== "—");
      const row = button?.closest("tr");
      const cell = button?.closest("td");
      return {
        candidate: button && row && cell ? {
          label: button.getAttribute("aria-label"),
          value: button.innerText.trim(),
          row: [...row.parentElement.children].indexOf(row),
          col: [...row.children].indexOf(cell) - 1
        } : null,
        diagnostics: {
          buttons: buttons.length,
          enabled: buttons.filter(e => !e.disabled).length,
          first: buttons.slice(0, 4).map(e => ({ text: e.innerText.trim(), label: e.getAttribute("aria-label"), tag: e.closest("td")?.tagName || e.closest("th")?.tagName || "" })),
          referenceMode: document.querySelector(".fm-reference-fieldset")?.disabled
        }
      };
    })()`);
    const capexEditCell = capexEditInfo.candidate;
    assert.ok(capexEditCell, `No editable CAPEX period cell was found: ${JSON.stringify(capexEditInfo.diagnostics)}`);
    const editedCapexSelector = `.fm-period-table tbody tr:nth-child(${capexEditCell.row + 1}) > td:nth-child(${capexEditCell.col + 2}) button.fm-period-cell-button`;
    await page.clickAria(capexEditCell.label);
    await page.press("Enter");
    const capexBuffer = await page.evaluate('document.querySelector(".fm-period-input")?.value || ""');
    assert.ok(capexBuffer, "CAPEX cell did not enter edit mode");
    await page.replaceFocusedText(String(Number(capexBuffer) + 0.1));
    await page.press("Enter");
    await page.waitFor("document.querySelector('.fm-period-state')?.innerText.includes('UNSAVED')");
    await page.press("z", { ctrl: true });
    await sleep(200);
    const valueAfterUndo = Number(await page.evaluate(`document.querySelector(${JSON.stringify(editedCapexSelector)})?.innerText.trim() || "NaN"`));
    assert.equal(valueAfterUndo, Number(capexBuffer), "Ctrl+Z did not restore the edited CAPEX cell");
    await page.clickAria(capexEditCell.label);
    await page.press("F2");
    await page.replaceFocusedText(String(Number(capexBuffer) + 0.1));
    await page.press("Enter");
    await page.waitFor("document.querySelector('.fm-period-state')?.innerText.includes('UNSAVED')");
    const metricLeftBefore = await page.evaluate("document.querySelector('.fm-period-metric')?.getBoundingClientRect().left || 0");
    await page.clickAria("Scroll periods right");
    const scroll = await page.evaluate(`(() => {
      const scroller = document.querySelector(".fm-period-scroll");
      const header = scroller?.querySelector("thead th");
      const metric = scroller?.querySelector(".fm-period-metric");
      return {
        left: scroller?.scrollLeft || 0,
        stickyHeader: getComputedStyle(header || document.body).position,
        stickyMetric: getComputedStyle(metric || document.body).position,
        metricLeft: metric?.getBoundingClientRect().left || 0,
        verticalScrollable: Boolean(scroller && scroller.scrollHeight > scroller.clientHeight + 1),
        scrollerTop: scroller?.getBoundingClientRect().top || 0,
        headerTop: header?.getBoundingClientRect().top || 0,
        scrollHeight: scroller?.scrollHeight || 0,
        clientHeight: scroller?.clientHeight || 0
      };
    })()`);
    assert.ok(scroll.left > 0, "Period scroll control did not move the grid");
    assert.equal(scroll.stickyHeader, "sticky");
    assert.equal(scroll.stickyMetric, "sticky");
    assert.ok(Math.abs(scroll.metricLeft - metricLeftBefore) <= 2, "CAPEX first metric column did not remain anchored during horizontal scroll");
    let verticalSticky = "no internal vertical overflow to test";
    if (scroll.verticalScrollable) {
      await page.evaluate('document.querySelector(".fm-period-scroll").scrollTop = 120');
      const afterVertical = await page.evaluate(`(() => {
        const scroller = document.querySelector(".fm-period-scroll");
        const header = scroller?.querySelector("thead th");
        return { top: header?.getBoundingClientRect().top || 0, scrollerTop: scroller?.getBoundingClientRect().top || 0, scrollTop: scroller?.scrollTop || 0 };
      })()`);
      assert.ok(afterVertical.scrollTop > 0 && Math.abs(afterVertical.top - afterVertical.scrollerTop) <= 2, `Vertical sticky header failed: ${JSON.stringify(afterVertical)}`);
      verticalSticky = "actual vertical scroll held the period header at the scroll-container top";
    }
    await page.clickId("finco-line-save");
    assert.match(await page.evaluate("document.querySelector('.fm-period-state')?.innerText || ''"), /LOCAL DEMO SAVE · NOT RUN/i);
    const pasteCell = await page.evaluate(`(() => {
      const rows = [...document.querySelectorAll(".fm-period-table tbody tr")];
      for (let row = 0; row < rows.length; row++) {
        const cells = [...rows[row].querySelectorAll("td")];
        for (let col = 0; col < cells.length - 1; col++) {
          const first = cells[col].querySelector("button.fm-period-cell-button:not(:disabled)");
          const second = cells[col + 1].querySelector("button.fm-period-cell-button:not(:disabled)");
          if (first && second && first.innerText.trim() !== "—" && second.innerText.trim() !== "—") {
            return { row, col, label: first.getAttribute("aria-label") };
          }
        }
      }
      return null;
    })()`);
    assert.ok(pasteCell, "No adjacent editable CAPEX period cells for browser TSV paste");
    const pasteSelector = `.fm-period-table tbody tr:nth-child(${pasteCell.row + 1}) > td:nth-child(${pasteCell.col + 2}) button.fm-period-cell-button`;
    const beforePaste = await page.evaluate(`(() => {
      const cells = document.querySelectorAll(".fm-period-table tbody tr")[${pasteCell.row}]?.querySelectorAll("td");
      return [cells?.[${pasteCell.col}]?.innerText.trim() || "", cells?.[${pasteCell.col + 1}]?.innerText.trim() || ""];
    })()`);
    const validPaste = await page.dispatchPaste(pasteSelector, "0.11\t0.22");
    assert.equal(validPaste.found, true);
    assert.equal(validPaste.prevented, true, "CAPEX period paste handler did not intercept the browser clipboard event");
    await page.waitFor("document.querySelector('.fm-period-state')?.innerText.includes('UNSAVED')");
    const afterValidPaste = await page.evaluate(`(() => {
      const cells = document.querySelectorAll(".fm-period-table tbody tr")[${pasteCell.row}]?.querySelectorAll("td");
      return [cells?.[${pasteCell.col}]?.innerText.trim() || "", cells?.[${pasteCell.col + 1}]?.innerText.trim() || ""];
    })()`);
    assert.notDeepEqual(afterValidPaste, beforePaste, "Valid CAPEX TSV did not stage the rectangle");
    await page.dispatchPaste(pasteSelector, "0.33\t-0.44");
    await page.waitFor("Boolean(document.querySelector('[role=alert]'))");
    const afterInvalidPaste = await page.evaluate(`(() => {
      const cells = document.querySelectorAll(".fm-period-table tbody tr")[${pasteCell.row}]?.querySelectorAll("td");
      return [cells?.[${pasteCell.col}]?.innerText.trim() || "", cells?.[${pasteCell.col + 1}]?.innerText.trim() || ""];
    })()`);
    assert.deepEqual(afterInvalidPaste, afterValidPaste, "Invalid CAPEX TSV partially changed the browser draft");
    await page.clickExpression(`document.querySelector(${JSON.stringify(pasteSelector)})`);
    await page.evaluate(`document.querySelector(${JSON.stringify(pasteSelector)})?.focus()`);
    await page.press("F2");
    assert.equal(await page.evaluate('Boolean(document.querySelector(".fm-period-input"))'), true, "CAPEX cell did not re-enter edit mode to resolve rejected paste");
    await page.press("Escape");
    await page.waitFor("!document.querySelector('[role=alert]')");
    await page.clickId("finco-line-save");
    assert.match(await page.evaluate("document.querySelector('.fm-period-state')?.innerText || ''"), /LOCAL DEMO SAVE · NOT RUN/i);

    await page.goto("ModelWorkspace");
    await page.clickNavHref("sheet=opex");
    await page.waitFor("Boolean(document.querySelector('.fm-period-scroll'))");
    const q = await page.evaluate("document.querySelectorAll('.fm-period-table thead .fm-period-heading').length");
    assert.equal(q, 12);
    await page.chooseSelect("OPEX period view", "Quarterly · editable working copy");
    await page.chooseSelect("Workbook operation period display", "Semiannual (6M)");
    const h = await page.evaluate("document.querySelectorAll('.fm-period-table thead .fm-period-heading').length");
    assert.equal(h, 6);
    await page.chooseSelect("OPEX schedule horizon", "Long UX preview · 60Q / 30H");
    const renderStarted = Date.now();
    await page.chooseSelect("OPEX period view", "Quarterly · editable working copy");
    const renderElapsed = Date.now() - renderStarted;
    const extendedQuarterly = await page.evaluate("document.querySelectorAll('.fm-period-table thead .fm-period-heading').length");
    assert.equal(extendedQuarterly, 60);
    const periodCells = await page.evaluate("document.querySelectorAll('.fm-period-table tbody td').length");
    await page.chooseSelect("OPEX period view", "Semiannual · locked fixed view");
    const extendedSemiannual = await page.evaluate("document.querySelectorAll('.fm-period-table thead .fm-period-heading').length");
    assert.equal(extendedSemiannual, 30);
    await page.chooseSelect("OPEX period view", "Quarterly · editable working copy");
    const opexEditCell = await page.evaluate(`(() => {
      const button = [...document.querySelectorAll(".fm-period-table tbody button.fm-period-cell-button:not(:disabled)")].find(e => e.getClientRects().length && e.innerText.trim() && e.innerText.trim() !== "—");
      return button ? { label: button.getAttribute("aria-label"), value: button.innerText.trim() } : null;
    })()`);
    assert.ok(opexEditCell, "No editable quarterly OPEX period cell was found");
    await page.clickAria(opexEditCell.label);
    await page.press("Enter");
    const opexBuffer = await page.evaluate('document.querySelector(".fm-period-input")?.value || ""');
    assert.ok(opexBuffer, "Quarterly OPEX cell did not enter edit mode");
    await page.replaceFocusedText(String(Number(opexBuffer) + 0.1));
    await page.press("Enter");
    await page.waitFor("document.querySelector('.fm-period-state')?.innerText.includes('UNSAVED')");
    await page.clickId("finco-line-save");
    assert.match(await page.evaluate("document.querySelector('.fm-period-state')?.innerText || ''"), /LOCAL DEMO SAVE · NOT RUN/i);
    return `CAPEX 18M and OPEX 12Q/6H + 60Q/30H; editable cells, atomic valid/invalid CAPEX TSV, local Save/NOT RUN, horizontal anchoring; ${verticalSticky}; 60Q fixture ${periodCells} body cells, selection-to-render ${renderElapsed}ms (harness-inclusive)`;
  });

  await check("PPA and financing records retain separate local demo drafts", async () => {
    await page.viewport(1440);
    await page.goto("ModelWorkspace");
    await page.clickNavHref("sheet=revenue");
    await page.waitFor("Boolean(document.querySelector('[aria-label=\"Synthetic multi-contract PPA editor\"]'))");
    const field = await page.evaluate(`(() => {
      const input = [...document.querySelectorAll(".fm-wf-fields input")].find(e => e.getClientRects().length && !e.disabled && e.value);
      return input ? { value: input.value, type: input.type } : null;
    })()`);
    assert.ok(field, "No editable PPA control found");
    let editedValue;
    if (field.type === "date" && /^\d{4}-\d{2}-\d{2}$/.test(field.value)) {
      const nextDay = new Date(`${field.value}T00:00:00Z`);
      nextDay.setUTCDate(nextDay.getUTCDate() + 1);
      editedValue = nextDay.toISOString().slice(0, 10);
    } else if (Number.isFinite(Number(field.value)) && field.value.trim()) {
      editedValue = String(Number(field.value) + 1);
    } else {
      editedValue = `${field.value} · test`;
    }
    await page.evaluate('[...document.querySelectorAll(".fm-wf-fields input")].find(e => e.getClientRects().length && !e.disabled)?.focus()');
    assert.equal(await page.evaluate("document.activeElement?.tagName"), "INPUT", "Counterparty label did not focus its editable field");
    await page.replaceFocusedText(editedValue);
    await page.chooseSelect("PPA-A contract type", "Indexed");
    assert.match(await page.evaluate("document.body.innerText"), /Indexation mode/i);
    await page.chooseSelect("PPA-A contract type", "Scheduled");
    assert.match(await page.evaluate("document.body.innerText"), /Scheduled tariff markers/i);
    await page.chooseSelect("PPA-A contract type", "Fixed");
    await page.clickText("PPA-B", "button");
    const valueB = await page.evaluate('document.querySelector(".fm-wf-fields input")?.value || ""');
    await page.clickText("PPA-A", "button");
    const valueA = await page.evaluate('document.querySelector(".fm-wf-fields input")?.value || ""');
    assert.equal(valueA, editedValue, "PPA-A draft did not persist while switching contracts");
    assert.notEqual(valueB, valueA, "PPA-B unexpectedly shares the edited PPA-A value");
    await page.clickText("Save PPA-A demo", ".fm-wf-actions button");
    await page.waitFor('document.querySelector("[aria-label=\\"Synthetic multi-contract PPA editor\\"] .fm-wf-editor-head > span")?.innerText.includes("LOCAL SAVE")');
    await page.clickText("PPA-C", "button");
    const valueCOriginal = await page.evaluate('document.querySelector(".fm-wf-fields input")?.value || ""');
    const valueCEdited = Number.isFinite(Number(valueCOriginal)) && valueCOriginal.trim()
      ? String(Number(valueCOriginal) + 2)
      : `${valueCOriginal} · C test`;
    await page.evaluate('[...document.querySelectorAll(".fm-wf-fields input")].find(e => e.getClientRects().length && !e.disabled)?.focus()');
    await page.replaceFocusedText(valueCEdited);
    await page.clickText("PPA-A", "button");
    assert.equal(await page.evaluate('document.querySelector(".fm-wf-fields input")?.value || ""'), editedValue, "PPA-C edit changed PPA-A");
    await page.clickText("PPA-C", "button");
    assert.equal(await page.evaluate('document.querySelector(".fm-wf-fields input")?.value || ""'), valueCEdited, "PPA-C draft did not persist across contract switches");
    await page.clickText("Save PPA-C demo", ".fm-wf-actions button");
    await page.waitFor('document.querySelector("[aria-label=\\"Synthetic multi-contract PPA editor\\"] .fm-wf-editor-head > span")?.innerText.includes("LOCAL SAVE")');

    await page.goto("ModelWorkspace");
    await page.clickNavHref("sheet=senior-debt");
    await page.waitFor("Boolean(document.querySelector('[aria-label=\"Synthetic financing and capital structure\"]'))");
    const facilityLabels = await page.evaluate(`[...document.querySelectorAll("button")].map(b => b.innerText.trim()).filter(t => /Senior A|Senior B|Junior|SHL|Equity/i.test(t))`);
    assert.ok(facilityLabels.length >= 4, `Facility register options missing: ${facilityLabels.join(", ")}`);
    const facilityField = await page.evaluate(`(() => {
      const section = [...document.querySelectorAll(".fm-wf-section")].find(e => e.getClientRects().length && /assumptions/i.test(e.querySelector("h3")?.innerText || ""));
      const input = [...(section?.querySelectorAll(".fm-wf-fields input") || [])].find(e => e.getClientRects().length && !e.disabled && e.value);
      return input ? { value: input.value, sectionLabel: section.getAttribute("aria-label"), title: section.querySelector("h3")?.innerText } : null;
    })()`);
    assert.ok(facilityField, `No visible facility input found: ${JSON.stringify(await page.evaluate(`({
      active: document.querySelector(".fm-wb-tree a[aria-current=page]")?.innerText || "",
      url: location.href,
      visibleSections: [...document.querySelectorAll(".fm-wf-section")].filter(e => e.getClientRects().length).map(e => ({label:e.getAttribute("aria-label"), title:e.querySelector("h3")?.innerText}))
    })`))}`);
    const facilityOriginal = facilityField.value;
    const facilityEdited = Number.isFinite(Number(facilityOriginal)) && facilityOriginal.trim()
      ? String(Number(facilityOriginal) + 1)
      : `${facilityOriginal} · test`;
    await page.evaluate(`(() => {
      const section = [...document.querySelectorAll(".fm-wf-section")].find(e => e.getClientRects().length && /assumptions/i.test(e.querySelector("h3")?.innerText || ""));
      [...(section?.querySelectorAll(".fm-wf-fields input") || [])].find(e => e.getClientRects().length && !e.disabled)?.focus();
    })()`);
    assert.equal(await page.evaluate("document.activeElement?.tagName"), "INPUT", "Facility label did not focus its editable field");
    await page.replaceFocusedText(facilityEdited);
    await page.clickText("Senior Debt B", "button");
    await page.waitFor("document.querySelector('.fm-wf-section h3')?.innerText.includes('Senior Debt B')");
    const seniorBValue = await page.evaluate('document.querySelector(".fm-wf-section .fm-wf-fields input")?.value || ""');
    await page.clickText("Senior Debt A", "button");
    await page.waitFor("document.querySelector('.fm-wf-section h3')?.innerText.includes('Senior Debt A')");
    const seniorAValue = await page.evaluate('document.querySelector(".fm-wf-section .fm-wf-fields input")?.value || ""');
    assert.equal(seniorAValue, facilityEdited, "Senior A draft did not persist after facility switch");
    assert.notEqual(seniorBValue, seniorAValue, "Senior B unexpectedly shares the edited Senior A value");
    const saveVisibleFacility = async () => {
      const label = await page.evaluate('[...document.querySelectorAll(".fm-wf-actions .fm-btn-primary")].find(e => e.getClientRects().length)?.innerText || ""');
      assert.match(label, /^Save .+ demo$/, `Visible facility Save action was not clear: ${label}`);
      await page.clickText(label, ".fm-wf-actions .fm-btn-primary", true);
    };
    await saveVisibleFacility();
    for (const [name, testValue] of [["Junior", "21.7"], ["SHL", "22.8"], ["Equity", "23.9"]]) {
      const option = facilityLabels.find((label) => label.toLowerCase().includes(name.toLowerCase()));
      assert.ok(option, `Missing facility selector for ${name}`);
      await page.clickText(option, "button", true);
      await page.waitFor(`document.querySelector(".fm-wf-section h3")?.innerText.includes(${JSON.stringify(name)})`);
      const inputSelector = '.fm-wf-section .fm-wf-fields input:not(:disabled)';
      assert.ok(await page.evaluate(`Boolean(document.querySelector(${JSON.stringify(inputSelector)}))`), `${name} facility has no editable demo field`);
      await page.evaluate(`document.querySelector(${JSON.stringify(inputSelector)})?.focus()`);
      await page.replaceFocusedText(testValue);
      await page.clickText("Senior Debt A", "button");
      await page.clickText(option, "button", true);
      assert.equal(await page.evaluate(`document.querySelector(${JSON.stringify(inputSelector)})?.value || ""`), testValue, `${name} draft did not remain distinct after switching facilities`);
      await saveVisibleFacility();
    }
    await page.clickNavHref("sheet=sources-uses");
    assert.match(await page.evaluate("document.body.innerText"), /Sources\s*(?:&|and)\s*Uses/i);
    return "PPA-A/B/C drafts remain distinct; Fixed/Indexed/Scheduled editors switch; modified PPA and Senior A/Junior/SHL/Equity drafts were individually acknowledged with local Save; all fixture records stayed separate and Sources & Uses was reachable";
  });

  await check("six statement tabs, period switch, trace entry and return", async () => {
    await page.viewport(1440);
    await page.goto("ResultsAnalysis");
    const tabs = ["pl", "balance", "cashflow", "cfads", "debt", "sponsor"];
    for (const tab of tabs) {
      await page.clickId(`fm-sw-tab-${tab}`);
      assert.equal(await page.evaluate(`document.getElementById("fm-sw-tab-${tab}")?.getAttribute("aria-selected")`), "true");
    }
    await page.chooseSelect("VIEW Annual Model periods", "Model periods");
    const periods = await page.evaluate("document.querySelector('[aria-label$=\"scrollable financial periods\"]')?.innerText || ''");
    assert.match(periods, /model-period/i);
    await page.viewport(390);
    const beforeScroll = await page.evaluate(`(() => {
      const element = document.querySelector('[aria-label$="scrollable financial periods"]');
      return element ? { scrollWidth: element.scrollWidth, clientWidth: element.clientWidth, rect: element.getBoundingClientRect().toJSON(), overflowX: getComputedStyle(element).overflowX } : null;
    })()`);
    await page.evaluate('document.querySelector("[aria-label$=\\"scrollable financial periods\\"]")?.focus()');
    await page.press("ArrowRight");
    const scrollState = await page.evaluate(`(() => {
      const element = document.querySelector('[aria-label$="scrollable financial periods"]');
      return element ? { left: element.scrollLeft, scrollWidth: element.scrollWidth, clientWidth: element.clientWidth } : null;
    })()`);
    assert.ok(scrollState?.left > 0, `Statement table did not scroll horizontally: before=${JSON.stringify(beforeScroll)} after=${JSON.stringify(scrollState)}`);
    const trace = await page.evaluate(`(() => [...document.querySelectorAll("button[aria-label]")].find(b => /Open synthetic source trace/.test(b.getAttribute("aria-label") || ""))?.getAttribute("aria-label") || "")`);
    assert.ok(trace, "Statement value cells do not expose trace controls");
    await page.clickExpression(`(() => [...document.querySelectorAll("button[aria-label]")].find(b => /Open synthetic source trace/.test(b.getAttribute("aria-label") || "")))()`);
    assert.match(await page.evaluate("document.body.innerText"), /SYNTHETIC SOURCE TRACE/i);
    const traceHref = await page.evaluate('document.querySelector("a.fm-sw-trace-open")?.href || ""');
    assert.match(traceHref, /ModelWorkspace/, `Trace context link has unexpected destination: ${traceHref}`);
    console.log(`Statement trace link destination: ${traceHref}`);
    const tracePointerHit = await page.evaluate(`(() => {
      const link = document.querySelector("a.fm-sw-trace-open");
      if (!link) return null;
      link.scrollIntoView({ block: "center", inline: "nearest" });
      const rect = link.getBoundingClientRect();
      const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      const region = link.closest(".fm-sw-region");
      return { linkText: link.innerText.trim(), hitTag: hit?.tagName || "", hitClass: hit?.className?.toString() || "", hitIsLink: hit === link || link.contains(hit), linkRect: rect.toJSON(), regionScrollTop: region?.scrollTop || 0 };
    })()`);
    await page.clickExpression(`document.querySelector("a.fm-sw-trace-open")`);
    await new Promise((resolve) => setTimeout(resolve, 300));
    let traceLanding = await page.evaluate(`({
      href: location.href,
      pathname: location.pathname,
      returnNotice: document.querySelector(".fm-trace-return")?.innerText || "",
      heading: document.querySelector("h1")?.innerText || "",
      activeElement: document.activeElement?.tagName || ""
    })`);
    let traceActivation = "pointer click";
    if (!traceLanding.pathname.toLowerCase().includes("modelworkspace")) {
      traceActivation = "keyboard Enter after pointer click did not navigate";
      await page.evaluate('document.querySelector("a.fm-sw-trace-open")?.focus()');
      await page.press("Enter");
      await new Promise((resolve) => setTimeout(resolve, 500));
      traceLanding = await page.evaluate(`({
        href: location.href,
        pathname: location.pathname,
        returnNotice: document.querySelector(".fm-trace-return")?.innerText || "",
        heading: document.querySelector("h1")?.innerText || "",
        activeElement: document.activeElement?.tagName || ""
      })`);
    }
    assert.ok(traceLanding.pathname.toLowerCase().includes("modelworkspace") && traceLanding.returnNotice, `Statement trace did not return to its input context: ${JSON.stringify(traceLanding)}`);
    assert.match(await page.evaluate("document.body.innerText"), /Return to the selected statement trace/i);
    console.log(`Trace route activated by ${traceActivation}; pointer target=${JSON.stringify(tracePointerHit)}`);
    await page.clickText("Return to the selected statement trace", "a");
    await page.waitFor("location.pathname.includes('ResultsAnalysis') && Boolean(document.querySelector('.fm-kpi-grid'))");
    assert.match(await page.evaluate("document.body.innerText"), /Results & analysis/i);
    return `six statement tabs and annual/model periods; trace returned using ${traceActivation}; pointer target=${JSON.stringify(tracePointerHit)}`;
  });

  await check("scenario/history panels and remaining workbook catalog links respond", async () => {
    await page.viewport(1440);
    await page.goto("ResultsAnalysis");
    await page.clickText("Run history");
    assert.equal(await page.evaluate("document.querySelector('#history')?.getAttribute('aria-label')"), "Demo run history");
    await page.clickText("Scenario comparison");
    assert.equal(await page.evaluate("document.querySelector('#scenarios')?.getAttribute('aria-label')"), "Demo scenario comparison");
    await page.goto("ModelWorkspace");
    const links = await page.evaluate(`(() => [...document.querySelectorAll(".fm-wb-tree a")].map(a => ({
      text: a.querySelector("span")?.innerText.trim() || a.innerText.trim(),
      href: a.getAttribute("href") || ""
    })).filter(item => item.href))()`);
    assert.ok(links.length >= 25, `Expected workbook catalog destinations, found ${links.length}`);
    const unique = [...new Map(links.map((link) => [link.href, link])).values()];
    let reached = 0;
    for (const link of unique) {
      await page.clickExpression(`(() => [...document.querySelectorAll(".fm-wb-tree a")].find(a => (a.getAttribute("href") || "") === ${JSON.stringify(link.href)}))()`);
      await page.waitFor("Boolean(document.querySelector('h1'))");
      const heading = await page.evaluate("document.querySelector('h1')?.innerText || ''");
      assert.ok(heading, `Catalog destination did not render: ${link.text}`);
      reached += 1;
    }
    await page.goto("ModelWorkspace");
    await page.clickNavHref("sheet=sensitivity");
    assert.match(await page.evaluate("document.body.innerText"), /Sensitivity/i);
    const sensitivityHref = await page.evaluate("location.href");
    await page.clickNavHref("sheet=goal-seek");
    assert.match(await page.evaluate("document.body.innerText"), /Goal seek/i);
    const goalSeekHref = await page.evaluate("location.href");
    await page.evaluate("history.back()");
    await page.waitFor(`location.href === ${JSON.stringify(sensitivityHref)}`);
    assert.match(await page.evaluate("document.body.innerText"), /Sensitivity/i);
    await page.evaluate("history.forward()");
    await page.waitFor(`location.href === ${JSON.stringify(goalSeekHref)}`);
    assert.match(await page.evaluate("document.body.innerText"), /Goal seek/i);
    await page.clickNavHref("sheet=trust");
    assert.match(await page.evaluate("document.body.innerText"), /Trust/i);
    return `${reached} distinct workbook catalog links rendered; History/Scenario panels, Sensitivity, Goal Seek, Trust and browser Back/Forward respond`;
  });

  await check("I12C-01 Debt facility round-trip restores period, expansion, trace and scroll", async () => {
    await page.viewport(390);
    await page.goto("ResultsAnalysis?statement=debt");
    await page.waitFor("Boolean(document.querySelector('#fm-sw-facility'))");
    assert.equal(await page.evaluate("document.querySelector('#fm-sw-facility')?.value"), "senior");
    assert.match(await page.evaluate("document.querySelector('.fm-sw-subbar strong')?.innerText || ''"), /Debt schedule/i);
    assert.ok(await page.evaluate(`[...document.querySelectorAll(".fm-sw-table tbody th")].some(e => e.innerText.includes("Senior facility drawdown"))`));

    await page.chooseSelect("Statement facility", "Mezzanine");
    assert.equal(await page.evaluate("document.querySelector('#fm-sw-facility')?.value"), "mezzanine");
    assert.match(await page.evaluate("document.querySelector('.fm-sw-subbar strong')?.innerText || ''"), /Mezzanine facility debt schedule/);
    assert.ok(await page.evaluate(`[...document.querySelectorAll(".fm-sw-table tbody th")].some(e => e.innerText.includes("Mezzanine facility drawdown"))`));
    await page.chooseSelect("VIEW Annual Model periods", "Annual");
    assert.match(await page.evaluate("document.querySelector('.fm-sw-subbar')?.innerText || ''"), /Annual view/i);
    await page.chooseSelect("VIEW Annual Model periods", "Model periods");
    assert.match(await page.evaluate("document.querySelector('.fm-sw-subbar')?.innerText || ''"), /Selected period snapshots/i);

    await page.clickAria("Expand Mezzanine facility drawdown detail rows");
    await page.waitFor(`[...document.querySelectorAll(".fm-sw-table tbody th")].some(e => e.innerText.trim() === "Construction draw")`);
    assert.equal(await page.evaluate(`document.querySelector('[aria-label="Collapse Mezzanine facility drawdown detail rows"]')?.getAttribute("aria-expanded")`), "true");
    await page.clickAria("Collapse Mezzanine facility drawdown detail rows");
    assert.equal(await page.evaluate(`document.querySelector('[aria-label="Expand Mezzanine facility drawdown detail rows"]')?.getAttribute("aria-expanded")`), "false");
    await page.clickAria("Expand Mezzanine facility drawdown detail rows");

    await page.evaluate('document.querySelector(".fm-sw-region")?.focus()');
    await page.press("ArrowRight");
    await page.press("ArrowRight");
    const scrolled = await page.evaluate('document.querySelector(".fm-sw-region")?.scrollLeft || 0');
    assert.ok(scrolled > 0, "Model-period schedule did not scroll with focused arrow navigation");
    await page.clickExpression('document.querySelector(\'button[data-statement-row="mezz-draw"][data-statement-col="3"]\')');
    const trace = await page.evaluate(`(() => {
      const link = document.querySelector("a.fm-sw-trace-open");
      const params = link ? new URL(link.href).searchParams : null;
      return {
        row: document.querySelector(".fm-sw-active-cell")?.innerText || "",
        href: link?.href || "",
        facility: params?.get("returnFacility") || "",
        view: params?.get("returnView") || "",
        period: params?.get("returnPeriod") || "",
        scrollLeft: Number(params?.get("returnScrollLeft") || 0),
        expanded: params?.get("returnExpanded") || "",
        traceLabel: document.querySelector('button[data-statement-row="mezz-draw"][data-statement-col="3"]')?.getAttribute("aria-label") || ""
      };
    })()`);
    assert.match(trace.row, /Mezzanine facility drawdown/);
    assert.equal(trace.facility, "mezzanine");
    assert.equal(trace.view, "model");
    assert.equal(trace.period, "3");
    assert.ok(trace.scrollLeft > 0, `Trace did not capture horizontal scroll: ${JSON.stringify(trace)}`);
    assert.match(trace.expanded, /debt:mezz-draw/);
    await page.clickExpression('document.querySelector("a.fm-sw-trace-open")');
    await page.waitFor("location.pathname.includes('ModelWorkspace') && Boolean(document.querySelector('.fm-trace-return'))");
    const returnLinkFocused = await page.evaluate(`(() => {
      const link = document.querySelector(".fm-trace-return a");
      link?.focus();
      return document.activeElement === link;
    })()`);
    assert.equal(returnLinkFocused, true, "Statement trace return link could not receive keyboard focus");
    const returnHref = await page.evaluate('document.querySelector(".fm-trace-return a")?.href || ""');
    await page.press("Enter");
    try {
      await page.waitFor("location.pathname.includes('ResultsAnalysis')");
    } catch {
      const routeState = await page.evaluate(`({
        href: location.href,
        transferApp: Boolean(window.__FINCO_TRANSFER_APP__),
        transferBase: window.__FINCO_TRANSFER_BASE__ || null,
        hasTransferNavigate: typeof window.__FINCO_TRANSFER_NAVIGATE__ === "function",
        returnHref: ${JSON.stringify(returnHref)}
      })`);
      throw new Error(`Trace return did not restore Results route: ${JSON.stringify(routeState)}`);
    }
    await page.waitFor("Boolean(document.querySelector('#fm-sw-facility'))");
    await sleep(180);
    const restored = await page.evaluate(`(() => ({
      facility: document.querySelector("#fm-sw-facility")?.value || "",
      sheetSelected: document.querySelector("#fm-sw-tab-debt")?.getAttribute("aria-selected") || "",
      view: document.querySelector("#fm-sw-view")?.value || "",
      scrollLeft: document.querySelector(".fm-sw-region")?.scrollLeft || 0,
      trace: document.querySelector(".fm-sw-active-cell")?.innerText || "",
      rowCell: document.querySelector('button[data-statement-row="mezz-draw"][data-statement-col="3"]')?.getAttribute("aria-label") || "",
      expanded: document.querySelector('[aria-label="Collapse Mezzanine facility drawdown detail rows"]')?.getAttribute("aria-expanded") || "",
      childVisible: [...document.querySelectorAll(".fm-sw-table tbody th")].some(e => e.innerText.trim() === "Construction draw")
    }))()`);
    assert.equal(restored.facility, "mezzanine");
    assert.equal(restored.sheetSelected, "true");
    assert.equal(restored.view, "model");
    assert.ok(Math.abs(restored.scrollLeft - trace.scrollLeft) <= 3, `Horizontal scroll was not restored: ${JSON.stringify({ expected: trace.scrollLeft, actual: restored.scrollLeft })}`);
    assert.match(restored.trace, /Mezzanine facility drawdown/);
    assert.equal(restored.rowCell, trace.traceLabel);
    assert.equal(restored.expanded, "true");
    assert.equal(restored.childVisible, true);
    await page.chooseSelect("Statement facility", "Senior");
    assert.equal(await page.evaluate("document.querySelector('#fm-sw-facility')?.value"), "senior");
    assert.ok(await page.evaluate(`[...document.querySelectorAll(".fm-sw-table tbody th")].some(e => e.innerText.includes("Senior facility drawdown"))`));
    return "Chromium keyboard-select Senior → Mezzanine → Senior; verified distinct row labels, group content/aria-expanded, model period 3, trace URL context and restored horizontal scroll. Statement selector has Senior/Mezzanine only; Senior A/B are tested in Financing.";
  });

  await check("I12C-02 scenario/project drafts, history selection and 2/3-run compare stay isolated", async () => {
    await page.viewport(1440);
    const solar = "projectId=PRJ-0241&project=Adriatic%20Solar%20I&technology=Solar%20PV";
    const wind = "projectId=PRJ-0236&project=North%20Ridge%20Wind&technology=Onshore%20wind";
    await page.goto(`ResultsAnalysis?${solar}&scenario=base`);
    const fixedBefore = await page.evaluate(`({
      kpis: [...document.querySelectorAll(".fm-kpi-value")].map(e => e.innerText.trim()),
      runId: document.querySelector(".fm-wb-status strong")?.innerText || document.body.innerText.match(/DEMO-FIXED-018/)?.[0] || ""
    })`);
    assert.ok(fixedBefore.kpis.some(value => value.includes("12.46%")));

    await page.goto(`ModelWorkspace?${solar}&sheet=scenarios&scenario=base`);
    await page.typeIntoAria("Scenario power price delta", "4");
    await page.clickText("Save Base case demo");
    const savedBase = await page.evaluate(`(() => {
      const drafts=JSON.parse(sessionStorage.getItem("finco-design-demo:v2:PRJ-0241:scenario-drafts") || "{}");
      const saved=JSON.parse(sessionStorage.getItem("finco-design-demo:v2:PRJ-0241:scenario-saved") || "{}");
      return {
        status:document.querySelector('[aria-label="Synthetic scenario editor"] .fm-wf-editor-head > span')?.innerText || "",
        draft:drafts.base?.powerDelta,
        saved:saved.base?.powerDelta,
        differingFields:Object.keys(drafts.base || {}).filter(key => drafts.base[key] !== saved.base?.[key])
      };
    })()`);
    assert.equal(savedBase.draft, "4", `Base draft did not persist after Save: ${JSON.stringify(savedBase)}`);
    assert.equal(savedBase.saved, "4", `Base Save did not persist the matching draft: ${JSON.stringify(savedBase)}`);
    assert.match(savedBase.status, /LOCAL SAVE/, `Base status did not reflect local Save: ${JSON.stringify(savedBase)}`);
    assert.match(await page.evaluate('document.querySelector(".fm-info-note[role=status]")?.innerText || ""'), /Fixed results were not recalculated/);
    await page.clickText("Downside", "button", true);
    assert.equal(await page.evaluate('document.querySelector(\'input[aria-label="Scenario power price delta"]\')?.value'), "-12");
    await page.typeIntoAria("Scenario power price delta", "-17");
    await page.clickText("Save Downside demo");
    await page.clickText("Upside", "button", true);
    assert.equal(await page.evaluate('document.querySelector(\'input[aria-label="Scenario power price delta"]\')?.value'), "8");
    await page.typeIntoAria("Scenario power price delta", "14");
    await page.clickText("Save Upside demo");
    await page.clickText("Base case", "button", true);
    assert.equal(await page.evaluate('document.querySelector(\'input[aria-label="Scenario power price delta"]\')?.value'), "4");
    await page.clickText("Downside", "button", true);
    assert.equal(await page.evaluate('document.querySelector(\'input[aria-label="Scenario power price delta"]\')?.value'), "-17");
    await page.clickText("Upside", "button", true);
    assert.equal(await page.evaluate('document.querySelector(\'input[aria-label="Scenario power price delta"]\')?.value'), "14");
    assert.match(await page.evaluate('document.querySelector("[aria-label=\\"Synthetic scenario editor\\"] .fm-wf-editor-head > span")?.innerText || ""'), /LOCAL SAVE/);

    await page.goto(`ModelWorkspace?${wind}&sheet=scenarios&scenario=base`);
    assert.equal(await page.evaluate('document.querySelector(\'input[aria-label="Scenario power price delta"]\')?.value'), "0", "Wind inherited the Solar Base scenario draft");
    await page.typeIntoAria("Scenario power price delta", "6");
    await page.clickText("Save Base case demo");
    await page.goto(`ModelWorkspace?${solar}&sheet=scenarios&scenario=base`);
    assert.equal(await page.evaluate('document.querySelector(\'input[aria-label="Scenario power price delta"]\')?.value'), "4", "Solar Base scenario was changed by Wind");
    await page.goto(`ModelWorkspace?${wind}&sheet=scenarios&scenario=base`);
    assert.equal(await page.evaluate('document.querySelector(\'input[aria-label="Scenario power price delta"]\')?.value'), "6", "Wind Base scenario draft did not remain project-scoped");

    await page.goto(`ModelWorkspace?${solar}&sheet=scenarios&scenario=base`);
    const preRunState = await page.evaluate(`({
      path:location.pathname,
      runAriaDisabled:document.querySelector(".fm-toolbar .fm-btn-primary")?.getAttribute("aria-disabled"),
      status:document.querySelector(".fm-wb-status")?.innerText || "",
      scenarioState:[...document.querySelectorAll(".fm-wf-editor-head span")].map(e => e.innerText).join(" | "),
      scenarioStorage:(() => {
        const drafts=JSON.parse(sessionStorage.getItem("finco-design-demo:v2:PRJ-0241:scenario-drafts") || "{}");
        const saved=JSON.parse(sessionStorage.getItem("finco-design-demo:v2:PRJ-0241:scenario-saved") || "{}");
        return Object.keys(drafts).filter(id => JSON.stringify(drafts[id]) !== JSON.stringify(saved[id])).map(id => ({id, draft:drafts[id]?.powerDelta, saved:saved[id]?.powerDelta}));
      })()
    })`);
    await page.clickText("Run demo FIXED RESULTS", "button");
    await page.waitFor("location.pathname.includes('ResultsAnalysis') || Boolean(document.querySelector('.fm-info-note[role=status]'))");
    const runAfterScenario = await page.evaluate(`({
      path:location.pathname,
      message:document.querySelector(".fm-info-note[role=status]")?.innerText || "",
      runState:document.querySelector(".fm-wb-status")?.innerText || ""
    })`);
    assert.match(runAfterScenario.path, /ResultsAnalysis/, `Saved scenario drafts should reach fixed demo results; before=${JSON.stringify(preRunState)} after=${JSON.stringify(runAfterScenario)}`);

    await page.goto(`ModelWorkspace?${solar}&sheet=history`);
    assert.equal(await page.evaluate('document.querySelectorAll(".fm-wf-section[aria-label=\\"Fixed run history register\\"] tbody tr").length'), 3);
    await page.clickText("Open P90 context", ".fm-wf-section a");
    await page.waitFor("location.pathname.includes('ResultsAnalysis')");
    assert.equal(await page.evaluate('new URLSearchParams(location.search).get("scenario")'), "downside");
    await page.evaluate("history.back()");
    await page.waitFor("location.pathname.includes('ModelWorkspace') && new URLSearchParams(location.search).get('sheet') === 'history'");
    assert.equal(await page.evaluate('new URLSearchParams(location.search).get("projectId")'), "PRJ-0241");
    await page.evaluate("history.forward()");
    await page.waitFor("location.pathname.includes('ResultsAnalysis')");

    await page.goto(`ModelWorkspace?${solar}&sheet=run-compare`);
    const runCounts = [];
    runCounts.push(await page.evaluate('document.querySelectorAll(".fm-wf-run-picker input:checked").length'));
    await page.clickExpression('(() => [...document.querySelectorAll(".fm-wf-run-picker label")].find(e => e.innerText.includes("DEMO-FIXED-014"))?.querySelector("input"))()');
    runCounts.push(await page.evaluate('document.querySelectorAll(".fm-wf-run-picker input:checked").length'));
    const runHeaders = await page.evaluate('[...document.querySelectorAll(".fm-wf-period-table thead th")].map(e => e.innerText.trim())');
    assert.deepEqual(runCounts, [2, 3]);
    assert.equal(runHeaders.length, 4, "Three-run comparison should show a metric and three fixed run columns");
    const selectedIds = await page.evaluate('new URLSearchParams(location.search).get("runSet") || ""');
    assert.match(selectedIds, /DEMO-FIXED-014/);
    const fixedAfter = await page.evaluate(`({
      resultText: document.body.innerText.includes("fixed comparison context"),
      noSolver: /NO EXECUTION HISTORY/i.test(document.body.innerText)
    })`);
    assert.equal(fixedAfter.resultText, true);
    assert.equal(fixedAfter.noSolver, true, `Run compare did not disclose its fixed/no-execution state: ${JSON.stringify(fixedAfter)}`);

    await page.goto(`ModelWorkspace?${solar}&sheet=scenarios&scenario=base`);
    await page.clickText("Run demo FIXED RESULTS", "button");
    await page.waitFor("location.pathname.includes('ResultsAnalysis') || Boolean(document.querySelector('.fm-info-note[role=status]'))");
    assert.match(await page.evaluate("location.pathname"), /ResultsAnalysis/, "Saved scenario drafts should reach the fixed demo result route");
    await page.waitFor('document.querySelectorAll(".fm-kpi-value").length === 4');
    const fixedAfterRun = await page.evaluate('([...document.querySelectorAll(".fm-kpi-value")].map(e => e.innerText.trim()))');
    assert.deepEqual(fixedAfterRun, fixedBefore.kpis, "Scenario edits or demo Run changed fixed headline output");
    await page.clickText("Run history");
    assert.equal(await page.evaluate('document.querySelectorAll("#history tbody tr").length'), 3, "A demo Run fabricated a new history record");
    await page.goto("ProjectLibrary");
    const libraryHasReferenceMode = await page.evaluate(`[...document.querySelectorAll("button")].some(e => /Open reference Adriatic Solar I/.test(e.getAttribute("aria-label") || ""))`);
    assert.equal(libraryHasReferenceMode, true, "Project Library should expose a separate read-only Reference entry");
    return "Base/Downside/Upside values persisted independently; Solar/Wind Base drafts 4/6 stayed separated; history had 3 fixed rows, Back/Forward restored project; compare changed 2→3 runs; demo Run preserved KPIs/history. Reference-copy flow is covered separately by I13-A.";
  });

  await check("I12C-03 credit, sources/uses, gated delivery and analysis states are honest and reachable", async () => {
    await page.viewport(1440);
    await page.goto("ModelWorkspace");
    await page.clickText("Lender / credit decision", ".fm-wb-tree a");
    assert.match(await page.evaluate("document.body.innerText"), /CREDIT DECISION\s*·\s*NOT ASSESSED/i);
    const claimedCovenantPass = await page.evaluate(`[...document.querySelectorAll(".fm-credit-review tbody td")].some(e => /^(?:PASS|COMPLIANT)$/i.test(e.innerText.trim()))`);
    assert.equal(claimedCovenantPass, false, "No credit matrix cell may claim a covenant pass");
    await page.chooseSelect("Lender case", "P90 downside");
    await page.chooseSelect("Credit facility", "Senior Debt B");
    await page.chooseSelect("Credit period basis", "Model-period snapshots");
    const creditContext = await page.evaluate(`({
      case:document.querySelector('[aria-label="Lender case"]')?.value || "",
      facility:document.querySelector('[aria-label="Credit facility"]')?.value || "",
      basis:document.querySelector('[aria-label="Credit period basis"]')?.value || "",
      schedule:document.querySelector(".fm-credit-workspace .fm-wf-period-table")?.innerText || "",
      state:document.querySelector(".fm-credit-workspace .fm-wf-toolbar")?.innerText || ""
    })`);
    assert.equal(creditContext.case, "P90 downside");
    assert.equal(creditContext.facility, "Senior Debt B");
    assert.equal(creditContext.basis, "model");
    assert.match(creditContext.schedule, /2026 M10/);
    assert.match(creditContext.state, /NOT ASSESSED/);

    await page.goto("ModelWorkspace");
    await page.clickNavHref("sheet=sources-uses");
    const sourcesUses = await page.evaluate("document.body.innerText");
    assert.match(sourcesUses, /Sources\s*(?:&|and)\s*Uses/i);
    assert.match(sourcesUses, /NOT RECONCILED TO DRAFTS/i);
    assert.match(sourcesUses, /DSRA/i);
    assert.match(sourcesUses, /DSRF/i);

    await page.goto("ModelWorkspace");
    await page.clickText("Excel migration", ".fm-wb-tree a");
    const importState = await page.evaluate(`({
      body: document.body.innerText,
      fileInputs: [...document.querySelectorAll('input[type="file"]')].map(e => e.disabled),
      buttons: [...document.querySelectorAll("button")].filter(e => /import|upload|map workbook/i.test(e.innerText)).map(e => ({ text:e.innerText.trim(), disabled:e.disabled }))
    })`);
    assert.match(importState.body, /Excel migration review/i);
    assert.equal(importState.fileInputs.length, 1, "Migration should explicitly show its disabled file control");
    assert.ok(importState.fileInputs.every(Boolean), "Migration must not expose an enabled file import");
    assert.ok(importState.buttons.every(button => button.disabled), `Migration showed an enabled import action: ${JSON.stringify(importState.buttons)}`);

    await page.goto("ModelWorkspace");
    await page.clickText("Exports", ".fm-wb-tree a");
    const exportState = await page.evaluate(`({
      panel: document.querySelector('[aria-label="Export design preview"]')?.innerText || "",
      buttons: [...document.querySelectorAll("button")].filter(e => /export|download|generate/i.test(e.innerText)).map(e => ({ text:e.innerText.trim(), disabled:e.disabled }))
    })`);
    assert.match(exportState.panel, /Export center/i);
    assert.ok(exportState.buttons.length > 0 && exportState.buttons.every(button => button.disabled), `Export controls were not visibly gated: ${JSON.stringify(exportState.buttons)}`);

    await page.goto("ModelWorkspace");
    await page.clickNavHref("sheet=sensitivity");
    await page.chooseSelect("Sensitivity driver", "PPA tariff");
    assert.match(await page.evaluate("document.querySelector('caption')?.innerText || ''"), /driver: PPA tariff/i);
    assert.match(await page.evaluate("document.body.innerText"), /PRE-AUTHORED EXAMPLES/);
    await page.goto("ModelWorkspace");
    await page.clickNavHref("sheet=goal-seek");
    assert.match(await page.evaluate("document.body.innerText"), /SOLVER UNAVAILABLE/);
    assert.equal(await page.evaluate('[...document.querySelectorAll("button")].some(e => /Run Goal Seek/.test(e.innerText) && e.disabled)'), true);

    await page.goto("ModelWorkspace");
    await page.clickNavHref("sheet=diagnostics");
    assert.match(await page.evaluate("document.body.innerText"), /Financial statement integrity[\s\S]*NOT EVALUATED/i);
    await page.goto("ModelWorkspace");
    await page.clickNavHref("sheet=trust");
    assert.match(await page.evaluate("document.body.innerText"), /NOT CERTIFIED|NOT EVALUATED/i);
    assert.match(await page.evaluate("document.body.innerText"), /No engine connection|NOT CONNECTED/i);
    for (const [id, expected] of [
      ["advanced-revenue", /Merchant settlement|advanced revenue/i],
      ["developer-economics", /Developer Economics/i],
      ["developer-decision", /Developer Decision/i],
      ["acquisition", /Acquisition analysis/i],
      ["bess-storage", /BESS \/ Storage/i],
      ["data-center", /Data Center/i],
      ["ev-charging", /EV Charging/i],
    ]) {
      await page.goto("ModelWorkspace");
      await page.clickNavHref(`sheet=${id}`);
      const gate = await page.evaluate(`({
        text: document.querySelector(".fm-wb-module-gate")?.innerText || "",
        statuses: [...document.querySelectorAll(".fm-wb-module-gate .fm-status")].map(e => e.innerText)
      })`);
      assert.match(gate.text, expected, `${id} did not render its distinct capability-gate copy`);
      assert.ok(gate.statuses.some(status => /UNAVAILABLE \/ GATED/i.test(status)), `${id} lacks an explicit unavailable gate`);
    }
    return "Credit shows NOT ASSESSED/no covenant pass; S&U/reserves disclose not reconciled; import/export remain disabled; Sensitivity/Goal Seek/Diagnostics/Trust are distinct; advanced revenue, Developer, Acquisition, BESS, Data Center and EV destinations are visibly gated, not activated.";
  });

  await check("I12C-04 60/80/120-period responsive stress, keyboard, sticky and reduced-motion checks", async () => {
    const renderTrials = { 60: [], 80: [], 120: [] };
    const scrollTrialsMs = [];
    const focusTrialsMs = [];
    await page.viewport(1440);
    await page.goto("ModelWorkspace?sheet=opex");
    await page.waitFor("Boolean(document.querySelector('.fm-period-scroll'))");
    for (const target of ["60", "80", "60", "80", "120", "80", "120", "60", "120"]) {
      const duration = await page.evaluate(`(async () => {
        const select = document.querySelector('[aria-label="OPEX schedule horizon"]');
        const start = performance.now();
        select.value = ${JSON.stringify(target)};
        select.dispatchEvent(new Event("change", { bubbles: true }));
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        const count = document.querySelectorAll(".fm-period-table thead .fm-period-heading").length;
        if (count !== Number(${JSON.stringify(target)})) throw new Error("Wrong rendered period count: " + count);
        return performance.now() - start;
      })()`);
      renderTrials[target].push(Number(duration.toFixed(2)));
    }
    performanceEvidence.push({
      environment: "headless Chromium via CDP; per-horizon DOM change-to-two-animation-frames estimate; includes browser scheduling, not a user-perceived benchmark",
      renderTrialsMs: renderTrials,
    });
    for (const target of ["60", "80", "120"]) {
      const values = renderTrials[target];
      assert.equal(values.length, 3);
      assert.ok(values.every(value => Number.isFinite(value) && value >= 0));
    }

    await page.chooseSelect("OPEX schedule horizon", "Layout stress only · 120Q / 60H");
    await page.viewport(1440);
    let layout = await page.evaluate(`(() => {
      const scroller = document.querySelector(".fm-period-scroll");
      const metric = document.querySelector(".fm-period-metric");
      const header = document.querySelector(".fm-period-table thead th");
      return {
        viewport: innerWidth,
        document: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
        periods: document.querySelectorAll(".fm-period-table thead .fm-period-heading").length,
        scrollWidth: scroller?.scrollWidth || 0,
        clientWidth: scroller?.clientWidth || 0,
        headerPosition: getComputedStyle(header).position,
        metricPosition: getComputedStyle(metric).position,
        tail: document.querySelectorAll(".fm-period-table tbody tr")[1]?.querySelectorAll("td")[119]?.innerText.trim() || ""
      };
    })()`);
    assert.equal(layout.periods, 120);
    assert.ok(layout.document <= layout.viewport + 1, `120Q caused document overflow at 1440: ${JSON.stringify(layout)}`);
    assert.ok(layout.scrollWidth > layout.clientWidth, "120Q period table should scroll inside its own region");
    assert.equal(layout.headerPosition, "sticky");
    assert.equal(layout.metricPosition, "sticky");
    assert.equal(layout.tail, "—", "120Q tail should remain explicitly unavailable, not a fabricated zero");

    const focusBefore = await page.evaluate(`(() => {
      const cell = [...document.querySelectorAll(".fm-period-table tbody tr")][1]?.querySelectorAll("td")[59]?.querySelector("button:not(:disabled)");
      if (!cell) return null;
      cell.focus();
      return { label:cell.getAttribute("aria-label"), address:document.querySelector(".fm-period-address")?.innerText.trim() || "" };
    })()`);
    assert.ok(focusBefore?.label, "Editable period 60 should have an accessible keyboard target");
    await page.press("ArrowRight");
    const focusAfter = await page.evaluate(`(() => ({
      focused:document.activeElement?.getAttribute("aria-label") || "",
      address:document.querySelector(".fm-period-address")?.innerText.trim() || "",
      selected:document.activeElement?.getAttribute("tabindex") || ""
    }))()`);
    assert.ok(focusAfter.focused && focusAfter.focused !== focusBefore.label, "Arrow key did not move focus to another editable cell");
    assert.match(focusAfter.address, /^[A-Z]+\d+$/);
    assert.equal(focusAfter.selected, "0");
    const extraCell = await page.evaluate('document.querySelectorAll(".fm-period-table tbody tr")[1]?.querySelectorAll("td")[60]?.querySelector("button")?.disabled');
    assert.equal(extraCell, true, "Period 61 should be visibly locked in a >60Q stress view");

    const widths = [];
    for (const width of [1440, 900, 390]) {
      await page.viewport(width);
      layout = await page.evaluate(`(() => {
        const scroller = document.querySelector(".fm-period-scroll");
        return {
          viewport: innerWidth,
          document: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
          scrollWidth: scroller?.scrollWidth || 0,
          clientWidth: scroller?.clientWidth || 0,
          top: scroller?.getBoundingClientRect().top || 0,
          headerTop: scroller?.querySelector("thead th")?.getBoundingClientRect().top || 0,
          verticalScrollable: Boolean(scroller && scroller.scrollHeight > scroller.clientHeight + 1)
        };
      })()`);
      assert.ok(layout.document <= width + 1, `OPEX 120Q document overflow at ${width}px: ${JSON.stringify(layout)}`);
      assert.ok(layout.scrollWidth > layout.clientWidth, `OPEX 120Q lost internal horizontal scroll at ${width}px`);
      widths.push({ width, document: layout.document, innerScroll: layout.scrollWidth > layout.clientWidth });
      if (width === 390) {
        await page.wheel(".fm-period-scroll", 600, 260);
        const afterWheel = await page.evaluate(`(() => {
          const scroller = document.querySelector(".fm-period-scroll");
          const metric = scroller?.querySelector(".fm-period-metric");
          return {
            left: scroller?.scrollLeft || 0,
            top: scroller?.scrollTop || 0,
            metricLeft: metric?.getBoundingClientRect().left || 0,
            scrollerLeft: scroller?.getBoundingClientRect().left || 0,
            headerPosition: getComputedStyle(scroller?.querySelector("thead th") || document.body).position,
            headerTop: scroller?.querySelector("thead th")?.getBoundingClientRect().top || 0,
            scrollerTop: scroller?.getBoundingClientRect().top || 0,
            verticalScrollable: Boolean(scroller && scroller.scrollHeight > scroller.clientHeight + 1)
          };
        })()`);
        assert.ok(afterWheel.left > 0, "Actual horizontal wheel did not scroll the OPEX table");
        assert.ok(Math.abs(afterWheel.metricLeft - afterWheel.scrollerLeft) <= 3, "Frozen metric label did not remain anchored during horizontal wheel scroll");
        if (afterWheel.verticalScrollable) {
          assert.ok(afterWheel.top > 0, "Actual vertical wheel did not scroll the table region");
          assert.ok(Math.abs(afterWheel.headerTop - afterWheel.scrollerTop) <= 3, "Sticky header did not remain at the scroll-region top");
        }
        for (let trial = 0; trial < 3; trial += 1) {
          const scrollStarted = Date.now();
          await page.wheel(".fm-period-scroll", trial % 2 ? -220 : 220, 0);
          scrollTrialsMs.push(Date.now() - scrollStarted);
          await page.evaluate("document.querySelector('.fm-period-table tbody button[tabindex=\"0\"]')?.focus()");
          const focusStarted = await page.evaluate("performance.now()");
          await page.press("ArrowRight");
          focusTrialsMs.push(Number((await page.evaluate(`performance.now() - ${focusStarted}`)).toFixed(2)));
        }
        await page.screenshot("i16-opex-120q-390.png");
      }
    }
    performanceEvidence.push({
      environment: "headless Chromium via CDP; wheel/focus timings include test-harness dispatch and wait overhead; not a user-perceived benchmark",
      horizontalWheelTrialsMs: scrollTrialsMs,
      keyboardFocusTrialsMs: focusTrialsMs,
    });
    await page.evaluate('document.querySelector(".fm-period-scroll")?.focus()');
    const aria = await page.evaluate(`({
      regionRole:document.querySelector(".fm-period-scroll")?.getAttribute("role") || "",
      regionLabel:document.querySelector(".fm-period-scroll")?.getAttribute("aria-label") || "",
      selectedCellTabindex:document.querySelector(".fm-period-table tbody button[tabindex=\\"0\\"]")?.getAttribute("tabindex") || "",
      errorAnnouncement:document.querySelector(".fm-period-message[role=\\"alert\\"]") ? "available when validation fails" : "not active in valid state"
    })`);
    assert.equal(aria.regionRole, "region");
    assert.match(aria.regionLabel, /OPEX period spreadsheet/);
    assert.equal(aria.selectedCellTabindex, "0");
    const contrast = await page.evaluate(`(() => {
      const parse = (value) => {
        const match = value.match(/rgba?\\(([^)]+)\\)/);
        if (!match) return null;
        const parts = match[1].split(",").map(part => Number.parseFloat(part.trim()));
        return { rgb:parts.slice(0,3), alpha:parts.length > 3 ? parts[3] : 1 };
      };
      const background = (element) => {
        const chain = [];
        for (let node = element; node; node = node.parentElement) chain.push(node);
        let color = [255,255,255];
        for (const node of chain.reverse()) {
          const layer = parse(getComputedStyle(node).backgroundColor);
          if (layer && layer.alpha > 0) color = layer.rgb.map((channel,index) => channel * layer.alpha + color[index] * (1-layer.alpha));
        }
        return color;
      };
      const luminance = (channels) => channels.map(value => {
        const n = value / 255;
        return n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4;
      }).reduce((sum,value,index) => sum + value * [0.2126,0.7152,0.0722][index],0);
      return [".fm-period-state",".fm-period-table thead th",".fm-period-metric"].map(selector => {
        const element = document.querySelector(selector);
        const foreground = parse(element ? getComputedStyle(element).color : "");
        const bg = element ? background(element) : null;
        const fg = foreground?.rgb || [0,0,0];
        const l1 = luminance(fg), l2 = luminance(bg || [255,255,255]);
        return { selector, text:element?.innerText.trim() || "", ratio:Number(((Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05)).toFixed(2)), color:getComputedStyle(element || document.body).color, background:bg };
      });
    })()`);
    accessibilityEvidence.push({ method:"Computed foreground/background contrast sample; no axe or screen-reader audit", samples:contrast });
    assert.equal(contrast.length, 3);
    for (const sample of contrast) assert.ok(sample.ratio >= 4.5, `Sampled text contrast below 4.5: ${JSON.stringify(sample)}`);

    await page.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
    await page.goto("ResultsAnalysis");
    await page.waitFor("Boolean(document.querySelector('.fm-sw-region'))");
    await page.evaluate(`(() => {
      const region = document.querySelector(".fm-sw-region");
      const original = region.scrollBy.bind(region);
      region.scrollBy = options => { window.__fincoScrollBehavior = options.behavior; return original(options); };
    })()`);
    await page.clickAria("Scroll statement periods right");
    const reducedBehavior = await page.evaluate("window.__fincoScrollBehavior || ''");
    assert.equal(reducedBehavior, "auto", "Reduced-motion preference should avoid smooth scrolling");
    await page.send("Emulation.setEmulatedMedia", { features: [] });
    return `120Q table kept overflow inside the grid at 1440/900/390; 60Q remained editable and >60Q tail locked; focus/label/header ARIA and reduced-motion scroll=auto passed; render trials ms ${JSON.stringify(renderTrials)}; wheel ms ${JSON.stringify(scrollTrialsMs)}; focus ms ${JSON.stringify(focusTrialsMs)}; 390px sticky vertical header ${layout.verticalScrollable ? "tested" : "no internal vertical overflow to exercise"}.`;
  });

  await check("no uncaught browser errors during exercised journeys", async () => {
    assert.deepEqual(page.consoleErrors, []);
    return `no captured Runtime exception, console.error or browser-log error; ${page.previewLifecycleNotes.length} transient Vite HMR/WebSocket Back-Forward Cache notices recorded separately (preview token redacted)`;
  });
} catch (error) {
  cases.push({ name: "browser harness setup", status: "FAIL", detail: error.message });
  console.error(`FAIL browser harness setup — ${error.stack || error.message}`);
} finally {
  await page.close();
}

const summary = {
  checks: cases.length,
  passed: cases.filter((item) => item.status === "PASS").length,
  failed: cases.filter((item) => item.status === "FAIL").length,
  cases,
  performanceEvidence,
  accessibilityEvidence,
  previewLifecycleNotes: page.previewLifecycleNotes,
  screenshots: [
    "test-evidence/i16-library-1440.png",
    "test-evidence/i16-workspace-900.png",
    "test-evidence/i16-results-390.png",
    "test-evidence/i16-opex-120q-390.png",
    "test-evidence/i16-reference-copy-390.png",
    "test-evidence/i16-mobile-statement-390.png",
    "test-evidence/i16-transfer-library-1440.png",
    "test-evidence/i16-transfer-library-900.png",
    "test-evidence/i16-transfer-workspace-900.png",
    "test-evidence/i16-transfer-workspace-390.png",
    "test-evidence/i16-transfer-results-1440.png",
    "test-evidence/i16-transfer-results-900.png",
    "test-evidence/i16-transfer-results-390.png",
  ],
};
await mkdir(evidenceDir, { recursive: true });
await writeFile(path.join(evidenceDir, "iteration-16-browser-results.json"), `${JSON.stringify(summary, null, 2)}\n`);
console.log(`\nBrowser acceptance: ${summary.passed}/${summary.checks} passed; ${summary.failed} failed.`);
if (summary.failed) process.exitCode = 1;
