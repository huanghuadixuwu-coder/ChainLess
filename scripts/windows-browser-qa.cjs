#!/usr/bin/env node

const fs = require("fs");
const http = require("http");
const path = require("path");
const { apiBaseFor } = require("./qa/api-client.cjs");
const { apiRequest } = require("./qa/api-client.cjs");
const { cleanupConversations } = require("./qa/cleanup-registry.cjs");
const { getSuite, registerSuite } = require("./qa/suite-registry.cjs");
const { createArtifactsSuite } = require("./qa/artifacts-suite.cjs");
const { createFileTaskClosureSuite } = require("./qa/file-task-closure-suite.cjs");
const { createRichInputSuite } = require("./qa/rich-input-suite.cjs");
const { createSpecCompleteSuite } = require("./qa/spec-complete.cjs");
const { createCapabilityLayerSuite } = require("./qa/capability-layer-suite.cjs");
const { createCapabilityAcquisitionSuite } = require("./qa/acquisition-suite.cjs");

function parseArgs(argv) {
  const args = {
    url: "",
    browser: "chrome",
    headed: true,
    keepOpen: false,
    timeoutMs: 20000,
    reportDir: path.resolve(process.cwd(), ".gstack", "qa-reports", "local"),
    waitForTextGone: "Loading",
    screenshotName: "page.png",
    suite: "smoke",
    tenant: "default",
    username: "admin",
    password: "admin123",
    chatUsername: "",
    chatPassword: "",
    apiUrl: "",
    credentialsExplicit: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--url") args.url = argv[++i] || "";
    else if (arg === "--browser") args.browser = argv[++i] || "chrome";
    else if (arg === "--headless") args.headed = false;
    else if (arg === "--headed") args.headed = true;
    else if (arg === "--keep-open") args.keepOpen = true;
    else if (arg === "--timeout-ms") args.timeoutMs = Number(argv[++i] || "20000");
    else if (arg === "--report-dir") args.reportDir = path.resolve(argv[++i] || args.reportDir);
    else if (arg === "--wait-for-text-gone") args.waitForTextGone = argv[++i] || "";
    else if (arg === "--screenshot-name") args.screenshotName = argv[++i] || "page.png";
    else if (arg === "--suite") args.suite = argv[++i] || "smoke";
    else if (arg === "--tenant") {
      args.tenant = argv[++i] || "default";
      args.credentialsExplicit = true;
    } else if (arg === "--username") {
      args.username = argv[++i] || "admin";
      args.credentialsExplicit = true;
    } else if (arg === "--password") {
      args.password = argv[++i] || "admin123";
      args.credentialsExplicit = true;
    }
    else if (arg === "--chat-username") args.chatUsername = argv[++i] || "";
    else if (arg === "--chat-password") args.chatPassword = argv[++i] || "";
    else if (arg === "--api-url") args.apiUrl = (argv[++i] || "").replace(/\/$/, "");
  }

  return args;
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function readDotEnvValue(name) {
  const envPath = path.resolve(process.cwd(), ".env");
  if (!fs.existsSync(envPath)) return "";
  const lines = fs.readFileSync(envPath, "utf8").split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const match = trimmed.match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (!match || match[1] !== name) continue;
    const raw = match[2].trim();
    if (
      (raw.startsWith('"') && raw.endsWith('"')) ||
      (raw.startsWith("'") && raw.endsWith("'"))
    ) {
      return raw.slice(1, -1);
    }
    return raw;
  }
  return "";
}

function applyBootstrapAdminCredentials(args) {
  if (args.credentialsExplicit) return;
  args.tenant = process.env.QA_ADMIN_TENANT || "default";
  args.username = process.env.QA_ADMIN_USERNAME || "admin";
  args.password =
    process.env.QA_ADMIN_PASSWORD ||
    process.env.BOOTSTRAP_ADMIN_PASSWORD ||
    readDotEnvValue("BOOTSTRAP_ADMIN_PASSWORD") ||
    "admin123";
}

function loadPlaywright() {
  try {
    return require("playwright");
  } catch (error) {
    const root = process.env.NODE_PATH;
    if (!root) throw error;

    const pnpmDir = path.join(root, ".pnpm");
    if (!fs.existsSync(pnpmDir)) throw error;

    const candidate = fs
      .readdirSync(pnpmDir)
      .find((name) => name.startsWith("playwright-core@"));

    if (!candidate) throw error;

    return require(path.join(pnpmDir, candidate, "node_modules", "playwright-core"));
  }
}

function nowStamp() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

function isIgnorableRequestFailure(url, errorText) {
  if (!errorText.includes("net::ERR_ABORTED")) return false;
  if (url.includes("_rsc=")) return true;
  if (url.includes("/favicon.ico")) return true;
  if (/\/api\/v1\/conversations\/[0-9a-f-]{36}$/i.test(url)) return true;
  return false;
}

async function waitForTextToDisappear(page, text, timeoutMs) {
  if (!text) return { ok: true, detail: "skip" };
  try {
    await page.waitForFunction(
      (needle) => !document.body || !document.body.innerText.includes(needle),
      text,
      { timeout: timeoutMs }
    );
    return { ok: true, detail: `text '${text}' disappeared` };
  } catch {
    return { ok: false, detail: `text '${text}' still visible after ${timeoutMs}ms` };
  }
}

async function screenshot(page, reportDir, name) {
  const file = path.join(reportDir, name);
  await page.screenshot({ path: file, fullPage: true }).catch(() => {});
  return file;
}

function readRequestBody(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    request.on("data", (chunk) => chunks.push(chunk));
    request.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    request.on("error", reject);
  });
}

async function startOpenAiMockServer(prefix, options = {}) {
  const mode = options.mode || "provider-switch";
  const calls = [];
  const server = http.createServer(async (request, response) => {
    try {
      if (request.method !== "POST") {
        response.writeHead(404, { "content-type": "application/json" });
        response.end(JSON.stringify({ error: "not found" }));
        return;
      }

      const bodyText = await readRequestBody(request);
      const body = bodyText ? JSON.parse(bodyText) : {};
      calls.push({ url: request.url, body });

      if (request.url.endsWith("/embeddings")) {
        response.writeHead(200, { "content-type": "application/json" });
        response.end(
          JSON.stringify({
            object: "list",
            data: [{ object: "embedding", index: 0, embedding: Array(1536).fill(0) }],
            model: body.model || "embedding-3",
          })
        );
        return;
      }

      if (request.url.endsWith("/chat/completions")) {
        const messages = Array.isArray(body.messages) ? body.messages : [];
        const lastUserMessage = [...messages]
          .reverse()
          .find((message) => message && message.role === "user");
        const prompt = String(lastUserMessage && lastUserMessage.content ? lastUserMessage.content : "")
          .toLowerCase();
        const lastMessage = messages[messages.length - 1] || {};
        const base = {
          id: "chatcmpl-chainless-qa",
          object: "chat.completion.chunk",
          created: Math.floor(Date.now() / 1000),
          model: body.model || "w5-browser-mock",
        };
        const writeFrame = (payload) => {
          response.write(`data: ${JSON.stringify(payload)}\n\n`);
        };
        const writeTextStream = (content) => {
          writeFrame({
            ...base,
            choices: [{ index: 0, delta: { content }, finish_reason: null }],
          });
          writeFrame({
            ...base,
            choices: [{ index: 0, delta: {}, finish_reason: "stop" }],
          });
          response.write("data: [DONE]\n\n");
          response.end();
        };
        const writeToolStream = (callId, name, args) => {
          writeFrame({
            ...base,
            choices: [
              {
                index: 0,
                delta: {
                  tool_calls: [
                    {
                      index: 0,
                      id: callId,
                      type: "function",
                      function: { name, arguments: "" },
                    },
                  ],
                },
                finish_reason: null,
              },
            ],
          });
          writeFrame({
            ...base,
            choices: [
              {
                index: 0,
                delta: {
                  tool_calls: [
                    {
                      index: 0,
                      function: { arguments: JSON.stringify(args) },
                    },
                  ],
                },
                finish_reason: null,
              },
            ],
          });
          writeFrame({
            ...base,
            choices: [{ index: 0, delta: {}, finish_reason: "tool_calls" }],
          });
          response.write("data: [DONE]\n\n");
          response.end();
        };

        if (body.stream) {
          response.writeHead(200, {
            "content-type": "text/event-stream",
            "cache-control": "no-cache",
            connection: "keep-alive",
          });
          if (mode === "workstream10") {
            if (lastMessage.role === "tool") {
              writeTextStream(`tool-result-ok:${prefix}`);
              return;
            }
            if (prompt.includes("web_fetch") || prompt.includes("example.com")) {
              writeToolStream(`call_${prefix}_web_fetch`, "web_fetch", {
                url: "https://example.com",
              });
              return;
            }
            if (prompt.includes("code_as_action") || prompt.includes("prints 42")) {
              writeToolStream(`call_${prefix}_code`, "code_as_action", {
                script: "print(42)",
              });
              return;
            }
            if (prompt.includes("shell_exec") || prompt.includes("date")) {
              writeToolStream(`call_${prefix}_shell`, "shell_exec", {
                command: "date",
              });
              return;
            }
            writeTextStream("WS10 chat SSE ok.");
            return;
          }

          writeTextStream(`provider-switch-ok:${prefix}`);
          return;
        }

        const content =
          mode === "workstream10"
            ? "WS10 chat SSE ok."
            : `provider-switch-ok:${prefix}`;
        response.writeHead(200, { "content-type": "application/json" });
        response.end(
          JSON.stringify({
            id: "chatcmpl-chainless-qa",
            object: "chat.completion",
            created: Math.floor(Date.now() / 1000),
            model: body.model || "w5-browser-mock",
            choices: [{ index: 0, message: { role: "assistant", content }, finish_reason: "stop" }],
          })
        );
        return;
      }

      response.writeHead(404, { "content-type": "application/json" });
      response.end(JSON.stringify({ error: "not found" }));
    } catch (error) {
      response.writeHead(500, { "content-type": "application/json" });
      response.end(JSON.stringify({ error: String(error) }));
    }
  });

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "0.0.0.0", () => {
      server.off("error", reject);
      resolve();
    });
  });

  const port = server.address().port;
  return {
    baseUrl: `http://host.docker.internal:${port}/v1`,
    calls,
    close: () => new Promise((resolve) => server.close(resolve)),
  };
}

async function loginViaUi(page, args) {
  await page.goto(args.url.replace(/\/$/, "") + "/login", {
    waitUntil: "domcontentloaded",
    timeout: args.timeoutMs,
  });
  await page.evaluate(() => {
    window.localStorage.removeItem("token");
    window.localStorage.removeItem("activeConversationId");
    window.localStorage.removeItem("theme");
  });
  const inputs = page.locator("form input");
  await inputs.nth(0).click();
  await page.keyboard.press(process.platform === "darwin" ? "Meta+A" : "Control+A");
  await page.keyboard.press("Backspace");
  await page.keyboard.type(args.tenant);
  await inputs.nth(1).click();
  await page.keyboard.press(process.platform === "darwin" ? "Meta+A" : "Control+A");
  await page.keyboard.press("Backspace");
  await page.keyboard.type(args.username);
  await inputs.nth(2).click();
  await page.keyboard.press(process.platform === "darwin" ? "Meta+A" : "Control+A");
  await page.keyboard.press("Backspace");
  await page.keyboard.type(args.password);
  const values = await inputs.evaluateAll((nodes) =>
    nodes.map((node) => node.value)
  );
  if (values[0] !== args.tenant || values[1] !== args.username || values[2] !== args.password) {
    throw new Error(`Login form fill failed: ${JSON.stringify(values)}`);
  }
  await page.getByRole("button", { name: "Sign In" }).click();
  await page.waitForURL(/\/chat/, { timeout: args.timeoutMs });
  await page.waitForLoadState("networkidle", { timeout: args.timeoutMs }).catch(() => {});
  return await page.evaluate(() => window.localStorage.getItem("token") || "");
}

async function prepareWorkstreamIdentity(apiBase, args) {
  if (args.credentialsExplicit) return;
  args.tenant = "qa-workstream10";
  args.username = "qa-runner";
  args.password = "qa-workstream10-only";
  const body = {
    tenant_name: args.tenant,
    username: args.username,
    password: args.password,
  };
  try {
    await apiRequest(apiBase, "/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(body),
    });
  } catch {
    await apiRequest(apiBase, "/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }
}

async function openSettingsSection(page, args, label, expectedText) {
  await page.getByRole("button", { name: label, exact: true }).click();
  await page
    .getByText(expectedText || label, { exact: true })
    .first()
    .waitFor({ timeout: args.timeoutMs });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function safeApiCall(label, fn) {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const value = await fn();
      return { label, ok: true, value, retried: attempt > 0 };
    } catch (error) {
      const message = String(error);
      if (
        message.includes("_NOT_FOUND") ||
        message.includes("404")
      ) {
        return { label, ok: true, alreadyRemoved: true };
      }
      if (message.includes("429") && attempt === 0) {
        await sleep(65000);
        continue;
      }
      return { label, ok: false, error: String(error), retried: attempt > 0 };
    }
  }
  return { label, ok: false, error: "unreachable safeApiCall state" };
}

async function cleanupSettingsArtifacts(apiBase, token, artifacts) {
  const results = [];
  if (artifacts.conversationIds.length) {
    const cleanup = await cleanupConversations(
      apiBase,
      token,
      artifacts.conversationIds
    );
    results.push({ label: "conversations", ok: cleanup.every((item) => item.ok), cleanup });
  }

  if (artifacts.toolName) {
    results.push(
      await safeApiCall("tool-risk-reset", () =>
        apiRequest(
          apiBase,
          `/api/v1/tools/${encodeURIComponent(artifacts.toolName)}/configuration`,
          {
            method: "PATCH",
            body: JSON.stringify({ risk_override: null }),
          },
          token
        )
      )
    );
  }

  for (const serverName of artifacts.mcpServerNames) {
    results.push(
      await safeApiCall(`mcp-delete-${serverName}`, () =>
        apiRequest(
          apiBase,
          `/api/v1/tools/${encodeURIComponent(serverName)}`,
          { method: "DELETE" },
          token
        )
      )
    );
  }

  for (const providerName of artifacts.providerNames) {
    results.push(
      await safeApiCall(`provider-delete-${providerName}`, () =>
        apiRequest(
          apiBase,
          `/api/v1/llm-providers/${encodeURIComponent(providerName)}`,
          { method: "DELETE" },
          token
        )
      )
    );
  }

  const agentPage = await safeApiCall("agents-list", () =>
    apiRequest(apiBase, "/api/v1/agents/?limit=100", {}, token)
  );
  if (agentPage.ok) {
    for (const agent of agentPage.value?.items || []) {
      if (artifacts.prefixes.some((prefix) => agent.name?.startsWith(prefix))) {
        results.push(
          await safeApiCall(`agent-delete-${agent.id}`, () =>
            apiRequest(
              apiBase,
              `/api/v1/agents/${encodeURIComponent(agent.id)}`,
              { method: "DELETE" },
              token
            )
          )
        );
      }
    }
  }

  const memoryPage = await safeApiCall("memories-list", () =>
    apiRequest(apiBase, "/api/v1/memories/?limit=100", {}, token)
  );
  if (memoryPage.ok) {
    for (const memory of memoryPage.value?.items || []) {
      if (artifacts.prefixes.some((prefix) => memory.name?.startsWith(prefix))) {
        results.push(
          await safeApiCall(`memory-delete-${memory.id}`, () =>
            apiRequest(
              apiBase,
              `/api/v1/memories/${encodeURIComponent(memory.id)}`,
              { method: "DELETE" },
              token
            )
          )
        );
      }
    }
  }

  const skillPage = await safeApiCall("skills-list", () =>
    apiRequest(apiBase, "/api/v1/skills/?limit=100", {}, token)
  );
  if (skillPage.ok) {
    for (const skill of skillPage.value?.items || []) {
      if (artifacts.prefixes.some((prefix) => skill.name?.startsWith(prefix))) {
        results.push(
          await safeApiCall(`skill-delete-${skill.id}`, () =>
            apiRequest(
              apiBase,
              `/api/v1/skills/${encodeURIComponent(skill.id)}`,
              { method: "DELETE" },
              token
            )
          )
        );
      }
    }
  }

  const proactivePage = await safeApiCall("proactive-list", () =>
    apiRequest(apiBase, "/api/v1/proactive-tasks?limit=100", {}, token)
  );
  if (proactivePage.ok) {
    for (const task of proactivePage.value?.items || []) {
      if (
        artifacts.prefixes.some((prefix) =>
          String(task.prompt || task.task_id || "").includes(prefix)
        )
      ) {
        results.push(
          await safeApiCall(`proactive-delete-${task.task_id}`, () =>
            apiRequest(
              apiBase,
              `/api/v1/proactive-tasks/${encodeURIComponent(task.task_id)}`,
              { method: "DELETE" },
              token
            )
          )
        );
      }
    }
  }

  return results;
}

async function runSmoke(page, args, reportDir) {
  const steps = [];
  let gotoOk = true;
  let gotoStatus = null;
  let gotoError = null;
  try {
    const response = await page.goto(args.url, {
      waitUntil: "domcontentloaded",
      timeout: args.timeoutMs,
    });
    gotoStatus = response ? response.status() : null;
    await page.waitForLoadState("networkidle", { timeout: args.timeoutMs }).catch(() => {});
  } catch (error) {
    gotoOk = false;
    gotoError = String(error);
  }

  const loadingCheck = await waitForTextToDisappear(
    page,
    args.waitForTextGone,
    Math.min(args.timeoutMs, 12000)
  );
  steps.push({ name: "smoke-navigation", ok: gotoOk && loadingCheck.ok, gotoStatus, loadingCheck, gotoError });
  return { steps, screenshots: [await screenshot(page, reportDir, args.screenshotName)] };
}

async function runWorkstream10(page, args, reportDir) {
  const apiBase = apiBaseFor(args.url, args.apiUrl);
  const prefix = `ws10-${Date.now()}`;
  const steps = [];
  const screenshots = [];
  const createdConversationIds = [];
  let token = "";
  let mockProvider = null;
  let providerName = "";

  try {
    await prepareWorkstreamIdentity(apiBase, args);
    token = await loginViaUi(page, args);
    if (!token) throw new Error("Login did not store a token");
    steps.push({ name: "auth-login", ok: true });
    screenshots.push(await screenshot(page, reportDir, "01-auth-login.png"));

    mockProvider = await startOpenAiMockServer(prefix, { mode: "workstream10" });
    providerName = `${prefix}-provider`;
    await apiRequest(
      apiBase,
      "/api/v1/llm-providers/",
      {
        method: "POST",
        body: JSON.stringify({
          name: providerName,
          api_base: mockProvider.baseUrl,
          api_key: `sk-${prefix}`,
          model: "w10-browser-mock",
          embedding_model: "embedding-3",
          is_default: true,
        }),
      },
      token
    );
    await apiRequest(
      apiBase,
      `/api/v1/llm-providers/${encodeURIComponent(providerName)}/default`,
      { method: "POST" },
      token
    );
    steps.push({ name: "mock-provider-default", ok: true, providerName });

    await page.getByRole("button", { name: "New Chat" }).first().click();
    await page.waitForFunction(() => Boolean(window.localStorage.getItem("activeConversationId")), null, {
      timeout: args.timeoutMs,
    });
    const crudConversationId = await page.evaluate(() => window.localStorage.getItem("activeConversationId"));
    createdConversationIds.push(crudConversationId);
    steps.push({ name: "conversation-create", ok: Boolean(crudConversationId), conversationId: crudConversationId });

    const renamedTitle = `WS10 QA ${Date.now()}`;
    page.once("dialog", async (dialog) => dialog.accept(renamedTitle));
    await page.locator('button[aria-label="Rename conversation"]').first().click({ force: true });
    await page.getByText(renamedTitle).waitFor({ timeout: args.timeoutMs });
    steps.push({ name: "conversation-rename", ok: true, title: renamedTitle });

    page.once("dialog", async (dialog) => dialog.accept());
    await page.locator('button[aria-label="Archive conversation"]').first().click({ force: true });
    await page.getByText(renamedTitle).waitFor({ state: "hidden", timeout: args.timeoutMs });
    steps.push({ name: "conversation-archive", ok: true });

    await page.getByRole("button", { name: "New Chat" }).first().click();
    await page.waitForFunction(() => Boolean(window.localStorage.getItem("activeConversationId")), null, {
      timeout: args.timeoutMs,
    });
    const chatConversationId = await page.evaluate(() => window.localStorage.getItem("activeConversationId"));
    createdConversationIds.push(chatConversationId);

    const input = page.getByPlaceholder(/Type a message/);
    await input.fill("Say exactly: WS10 chat SSE ok.");
    await page.keyboard.press("Control+Enter");
    await page.getByText("WS10 chat SSE ok.", { exact: true }).waitFor({ timeout: 60000 });
    steps.push({ name: "chat-sse", ok: true });
    screenshots.push(await screenshot(page, reportDir, "02-chat-sse.png"));

    await input.fill("Fetch the title of https://example.com using web_fetch.");
    await page.keyboard.press("Control+Enter");
    await page.getByText("web_fetch", { exact: true }).waitFor({ timeout: 60000 });
    steps.push({ name: "tool-card-web-fetch", ok: true });
    await page
      .getByText("https://example.com", { exact: false })
      .first()
      .waitFor({ timeout: args.timeoutMs });
    steps.push({ name: "tool-card-web-fetch-payload", ok: true });
    screenshots.push(await screenshot(page, reportDir, "03-tool-panel.png"));

    await input.fill("Use code_as_action to run Python that prints 42.");
    await page.keyboard.press("Control+Enter");
    await page.getByText("code_as_action", { exact: true }).waitFor({ timeout: 90000 });
    await page.getByText("42", { exact: true }).first().waitFor({ timeout: 90000 });
    const terminalButton = page.getByRole("button", { name: "Terminal" });
    if (!(await terminalButton.isVisible().catch(() => false))) {
      await page.getByTitle("Toggle preview").click();
    }
    await terminalButton.click();
    await page
      .getByRole("complementary")
      .getByText("42", { exact: true })
      .waitFor({ timeout: args.timeoutMs });
    steps.push({ name: "code-as-action", ok: true });
    screenshots.push(await screenshot(page, reportDir, "04-code-as-action.png"));

    await input.fill("Use shell_exec to run date.");
    await page.keyboard.press("Control+Enter");
    await page.getByText("Confirmation required").waitFor({ timeout: 60000 });
    await page.getByRole("button", { name: "Deny" }).click();
    await page.getByText("User denied this action.").first().waitFor({ timeout: 60000 });
    steps.push({ name: "destructive-confirmation-deny", ok: true });
    screenshots.push(await screenshot(page, reportDir, "05-destructive-confirmation.png"));
  } catch (error) {
    error.qaSteps = steps;
    error.qaScreenshots = screenshots;
    throw error;
  } finally {
    if (token && createdConversationIds.length) {
      const cleanup = await cleanupConversations(apiBase, token, createdConversationIds);
      steps.push({ name: "cleanup-conversations", ok: cleanup.every((item) => item.ok), cleanup });
    }
    if (token && providerName) {
      const cleanup = await safeApiCall("provider-delete", () =>
        apiRequest(
          apiBase,
          `/api/v1/llm-providers/${encodeURIComponent(providerName)}`,
          { method: "DELETE" },
          token
        )
      );
      steps.push({ name: "cleanup-mock-provider", ok: cleanup.ok, cleanup });
    }
    if (mockProvider) {
      await mockProvider.close().catch(() => {});
    }
    await page.evaluate(() => window.localStorage.removeItem("activeConversationId")).catch(() => {});
  }

  return { steps, screenshots };
}

async function runSettings(page, args, reportDir) {
  const apiBase = apiBaseFor(args.url, args.apiUrl);
  const steps = [];
  const screenshots = [];
  const stamp = Date.now();
  const prefix = `w5-final-${stamp}`;
  const artifacts = {
    prefixes: [prefix],
    conversationIds: [],
    providerNames: [],
    mcpServerNames: [],
    toolName: "",
  };
  let token = "";
  let mockProvider = null;

  try {
    applyBootstrapAdminCredentials(args);
    mockProvider = await startOpenAiMockServer(prefix);
    token = await loginViaUi(page, args);
    if (!token) throw new Error("Login did not store a token");
    steps.push({ name: "auth-login-admin", ok: true });

    await page.goto(args.url.replace(/\/$/, "") + "/settings", {
      waitUntil: "domcontentloaded",
      timeout: args.timeoutMs,
    });
    await page.waitForLoadState("networkidle", { timeout: args.timeoutMs }).catch(() => {});
    await page.getByText("Settings", { exact: true }).first().waitFor({ timeout: args.timeoutMs });
    steps.push({ name: "settings-route-open", ok: true });

    const sections = [
      ["Provider", "Provider"],
      ["Agent", "Agent"],
      ["Tools", "Tools"],
      ["Memories", "Memories"],
      ["Channel", "Feishu channel"],
      ["Proactive", "Proactive"],
      ["Skills", "Skills"],
      ["Eval", "Eval suites"],
      ["System", "Appearance"],
    ];
    for (const [label, expected] of sections) {
      await openSettingsSection(page, args, label, expected);
      steps.push({ name: `settings-section-${label.toLowerCase()}`, ok: true });
    }
    screenshots.push(await screenshot(page, reportDir, "01-settings-sections.png"));

    await openSettingsSection(page, args, "Provider", "Provider");
    const providerPageBefore = await apiRequest(
      apiBase,
      "/api/v1/llm-providers/?limit=100",
      {},
      token
    );
    if ((providerPageBefore.items || []).length === 0) {
      const baselineProviderName = `${prefix}-baseline-provider`;
      artifacts.providerNames.push(baselineProviderName);
      await apiRequest(
        apiBase,
        "/api/v1/llm-providers/",
        {
          method: "POST",
          body: JSON.stringify({
            name: baselineProviderName,
            api_base: mockProvider.baseUrl,
            api_key: `sk-${prefix}-baseline`,
            model: "w5-browser-mock",
            embedding_model: "embedding-3",
            is_default: true,
          }),
        },
        token
      );
      await page.reload({ waitUntil: "domcontentloaded", timeout: args.timeoutMs });
      await page.waitForLoadState("networkidle", { timeout: args.timeoutMs }).catch(() => {});
      await openSettingsSection(page, args, "Provider", "Provider");
    }
    const providerName = `${prefix}-provider`;
    artifacts.providerNames.push(providerName);
    const providerForm = page.locator("form").first();
    await providerForm.locator("input").nth(0).fill(providerName);
    await providerForm.locator("input").nth(1).fill(mockProvider.baseUrl);
    await providerForm.locator("input").nth(2).fill("w5-browser-mock");
    await providerForm.locator("input").nth(3).fill("embedding-3");
    await providerForm.locator("input").nth(4).fill(`sk-${prefix}-provider`);
    await providerForm.getByRole("button", { name: "Save provider" }).click();
    await page.getByText(providerName, { exact: true }).waitFor({ timeout: args.timeoutMs });
    await page.getByText(/API key:/).first().waitFor({ timeout: args.timeoutMs });
    const providerRow = page.locator("form").filter({ hasText: providerName }).last();
    await providerRow.getByRole("button", { name: "Make default" }).click();
    await page.waitForLoadState("networkidle", { timeout: args.timeoutMs }).catch(() => {});
    await page
      .locator("form")
      .filter({ hasText: providerName })
      .last()
      .getByText("default", { exact: true })
      .waitFor({ timeout: args.timeoutMs });
    steps.push({ name: "provider-create-mask-default", ok: true, providerName });

    await openSettingsSection(page, args, "Agent", "Agent");
    const agentName = `${prefix}-agent`;
    const agentForm = page.locator("form").first();
    await agentForm.locator("input").nth(0).fill(agentName);
    await agentForm.locator("input").nth(1).fill("default");
    await agentForm.locator("textarea").first().fill(`${prefix} active agent prompt`);
    await agentForm.getByRole("button", { name: "Save agent" }).click();
    await page.getByText(agentName, { exact: true }).waitFor({ timeout: args.timeoutMs });
    await page.getByText("active", { exact: true }).first().waitFor({ timeout: args.timeoutMs });
    steps.push({ name: "agent-create-active", ok: true, agentName });

    await openSettingsSection(page, args, "Tools", "Tools");
    const toolRows = page.locator('div[data-testid="tool-row"]');
    const toolCount = await toolRows.count().catch(() => 0);
    const firstToolRow = toolCount ? toolRows.first() : page.getByText("Available to agents").first().locator("..").locator("..");
    await page.getByText("Available to agents").first().waitFor({ timeout: args.timeoutMs });
    const riskSelect = page.locator("select").first();
    if ((await riskSelect.count()) > 0) {
      const toolName = await firstToolRow.locator(".font-medium").first().innerText().catch(() => "");
      artifacts.toolName = toolName.trim();
      await riskSelect.selectOption("safe");
      await page.getByText("Tool configuration updated.").waitFor({ timeout: args.timeoutMs }).catch(() => {});
      await riskSelect.selectOption("");
      steps.push({ name: "tool-risk-override-reset", ok: true, toolName: artifacts.toolName });
    } else {
      steps.push({ name: "tool-risk-override-reset", ok: false, error: "risk override select missing" });
    }

    const mcpServer = `${prefix.replace(/-/g, "")}mcp`;
    artifacts.mcpServerNames.push(mcpServer);
    const mcpForm = page.locator("form").first();
    await mcpForm.locator("input").nth(0).fill(mcpServer);
    await mcpForm.locator("input").nth(1).fill("python");
    await mcpForm.locator("input").nth(2).fill("scripts/mcp_echo_server.py");
    await mcpForm.locator("input").nth(3).fill("");
    await mcpForm.getByRole("button", { name: "Register MCP server" }).click();
    await page.getByText(mcpServer, { exact: true }).waitFor({ timeout: args.timeoutMs });
    const testerForm = page.locator("form").nth(1);
    await testerForm.locator("input").nth(0).fill(mcpServer);
    await testerForm.locator("input").nth(1).fill("echo");
    await testerForm.locator("textarea").first().fill('{"text":"w5 settings"}');
    await testerForm.getByRole("button", { name: "Test tool" }).click();
    await page.getByText("Tool test completed.").waitFor({ timeout: args.timeoutMs }).catch(() => {});
    steps.push({ name: "mcp-register-test", ok: true, mcpServer });

    await openSettingsSection(page, args, "Memories", "Memories");
    const memoryName = `${prefix}-memory`;
    const memoryForm = page.locator("form").first();
    await memoryForm.locator("input").nth(0).fill("user");
    await memoryForm.locator("input").nth(1).fill(memoryName);
    await memoryForm.locator("input").nth(2).fill("W5 final browser memory");
    await memoryForm.locator("input").nth(3).fill("w5-final");
    await memoryForm.locator("textarea").first().fill(`${prefix} memory context marker`);
    await memoryForm.getByRole("button", { name: "Save memory" }).click();
    await page.getByText(memoryName, { exact: true }).waitFor({ timeout: args.timeoutMs });
    const searchForm = page.locator("form").nth(1);
    await searchForm.locator("input").first().fill(prefix);
    await searchForm.getByRole("button", { name: "Search" }).click();
    await page.getByText(`${prefix} memory context marker`).waitFor({ timeout: args.timeoutMs });
    const mergeForm = page.locator("form").nth(2);
    await mergeForm.locator("textarea").first().fill(`Use ${prefix} memory`);
    await mergeForm.getByRole("button", { name: "Merge" }).click();
    await page.getByText(/Memories:/).waitFor({ timeout: args.timeoutMs });
    steps.push({ name: "memory-create-search-merge", ok: true, memoryName });

    await openSettingsSection(page, args, "Channel", "Feishu channel");
    await page.getByText("Webhook", { exact: false }).first().waitFor({ timeout: args.timeoutMs });
    await page.getByText("Signing secret", { exact: false }).first().waitFor({ timeout: args.timeoutMs });
    steps.push({ name: "channel-feishu-secret-surface", ok: true });

    await openSettingsSection(page, args, "Proactive", "Proactive");
    const proactivePrompt = `${prefix} proactive prompt`;
    const proactiveForm = page.locator("form").first();
    await proactiveForm.locator("input").nth(0).fill("0 9 * * *");
    await proactiveForm.locator("input").nth(1).fill("default");
    await proactiveForm.locator("input").nth(2).fill("feishu");
    await proactiveForm.locator("textarea").first().fill(proactivePrompt);
    await proactiveForm.getByRole("button", { name: "Save proactive task" }).click();
    await page.getByText(proactivePrompt).waitFor({ timeout: args.timeoutMs });
    await page.getByText("Run history", { exact: true }).waitFor({ timeout: args.timeoutMs });
    steps.push({ name: "proactive-create-runs-visible", ok: true });

    await openSettingsSection(page, args, "Skills", "Skills");
    const skillName = `${prefix}-skill`;
    const skillForm = page.locator("form").first();
    await skillForm.locator("input").nth(0).fill(skillName);
    await skillForm.locator("input").nth(1).fill("W5 final passive skill");
    await skillForm.locator("input").nth(2).fill(prefix);
    await skillForm.getByRole("button", { name: "Save skill" }).click();
    await page.getByText(skillName, { exact: true }).waitFor({ timeout: args.timeoutMs });
    await page.getByPlaceholder("Paste text to match against enabled skill triggers").fill(`trigger ${prefix}`);
    await page.getByRole("button", { name: "Test" }).click();
    await page.getByText("Matched:", { exact: false }).waitFor({ timeout: args.timeoutMs });
    steps.push({ name: "skill-create-match", ok: true, skillName });

    await openSettingsSection(page, args, "Eval", "Eval suites");
    const dryRunButtons = page.getByRole("button", { name: "Dry-run" });
    if ((await dryRunButtons.count()) > 0) {
      await dryRunButtons.first().click();
      await page.getByText("Last dry-run result", { exact: true }).waitFor({ timeout: args.timeoutMs });
      steps.push({ name: "eval-dry-run", ok: true });
    } else {
      steps.push({ name: "eval-dry-run", ok: true, skipped: "no suites" });
    }

    await openSettingsSection(page, args, "System", "Appearance");
    const defaultDark = await page.evaluate(() =>
      document.documentElement.classList.contains("dark")
    );
    await page.getByRole("button", { name: /Switch to Light/ }).click();
    await page.waitForFunction(() => !document.documentElement.classList.contains("dark"), null, {
      timeout: args.timeoutMs,
    });
    await page.getByRole("button", { name: /Switch to Dark/ }).click();
    await page.waitForFunction(() => document.documentElement.classList.contains("dark"), null, {
      timeout: args.timeoutMs,
    });
    await page.reload({ waitUntil: "domcontentloaded", timeout: args.timeoutMs });
    await page.waitForFunction(() => document.documentElement.classList.contains("dark"), null, {
      timeout: args.timeoutMs,
    });
    await page.waitForLoadState("networkidle", { timeout: args.timeoutMs }).catch(() => {});
    steps.push({ name: "theme-toggle-default-dark-persist", ok: defaultDark });
    screenshots.push(await screenshot(page, reportDir, "02-settings-system-theme.png"));

    if ((args.chatUsername && !args.chatPassword) || (!args.chatUsername && args.chatPassword)) {
      throw new Error("Both --chat-username and --chat-password are required when using chat credentials");
    }

    if (args.chatUsername && args.chatPassword) {
      token = await loginViaUi(page, {
        ...args,
        username: args.chatUsername,
        password: args.chatPassword,
      });
      if (!token) {
        throw new Error("Chat credential login did not store an access token");
      }
      steps.push({
        name: "auth-login-chat-admin",
        ok: true,
        username: args.chatUsername,
      });
    }

    await page.goto(args.url.replace(/\/$/, "") + "/chat", {
      waitUntil: "domcontentloaded",
      timeout: args.timeoutMs,
    });
    await page.getByRole("button", { name: "New Chat" }).first().click();
    await page.waitForFunction(() => Boolean(window.localStorage.getItem("activeConversationId")), null, {
      timeout: args.timeoutMs,
    });
    const chatConversationId = await page.evaluate(() =>
      window.localStorage.getItem("activeConversationId")
    );
    artifacts.conversationIds.push(chatConversationId);
    const input = page.getByPlaceholder(/Type a message/);
    await input.fill(`Use available context about ${prefix}.`);
    await page.keyboard.press("Control+Enter");
    await page.getByTestId("context-banner").waitFor({ timeout: args.timeoutMs });
    await page.getByText("Context loaded", { exact: true }).waitFor({ timeout: args.timeoutMs });
    await page.getByText(agentName, { exact: false }).first().waitFor({ timeout: args.timeoutMs });
    await page.getByText(`Provider: ${providerName}`, { exact: false }).waitFor({
      timeout: args.timeoutMs,
    });
    await page.getByText(`provider-switch-ok:${prefix}`, { exact: false }).waitFor({
      timeout: args.timeoutMs,
    });
    steps.push({
      name: "chat-context-banner-provider-switch",
      ok: true,
      conversationId: chatConversationId,
      providerName,
      mockCalls: mockProvider.calls
        .filter((call) => call.url.endsWith("/chat/completions"))
        .length,
    });
    screenshots.push(await screenshot(page, reportDir, "03-chat-context-banner.png"));
  } catch (error) {
    error.qaSteps = steps;
    error.qaScreenshots = screenshots;
    throw error;
  } finally {
    if (token) {
      const cleanup = await cleanupSettingsArtifacts(apiBase, token, artifacts);
      steps.push({
        name: "cleanup-settings-artifacts",
        ok: cleanup.every((item) => item.ok),
        cleanup,
      });
    }
    await page.evaluate(() => window.localStorage.removeItem("activeConversationId")).catch(() => {});
    if (mockProvider) {
      await mockProvider.close().catch(() => {});
    }
  }

  return { steps, screenshots };
}

registerSuite("smoke", runSmoke);
registerSuite("workstream10", runWorkstream10);
registerSuite("settings", runSettings);
registerSuite(
  "artifacts",
  createArtifactsSuite({
    apiBaseFor,
    apiRequest,
    cleanupConversations,
    safeApiCall,
    loginViaUi,
    screenshot,
    applyBootstrapAdminCredentials,
    readRequestBody,
  })
);
registerSuite(
  "rich-input",
  createRichInputSuite({
    apiBaseFor,
    apiRequest,
    cleanupConversations,
    safeApiCall,
    loginViaUi,
    screenshot,
    applyBootstrapAdminCredentials,
    readRequestBody,
  })
);
registerSuite(
  "file-task-closure",
  createFileTaskClosureSuite({
    apiBaseFor,
    apiRequest,
    cleanupConversations,
    safeApiCall,
    loginViaUi,
    screenshot,
    applyBootstrapAdminCredentials,
    readRequestBody,
  })
);
registerSuite(
  "spec-complete",
  createSpecCompleteSuite({
    apiBaseFor,
    apiRequest,
    loginViaUi,
    applyBootstrapAdminCredentials,
    runSmoke,
    runWorkstream10,
    runSettings,
    getSuite,
  })
);
registerSuite(
  "capability-layer",
  createCapabilityLayerSuite({
    apiBaseFor,
    apiRequest,
    cleanupConversations,
    safeApiCall,
    loginViaUi,
    screenshot,
    applyBootstrapAdminCredentials,
    readRequestBody,
  })
);
registerSuite(
  "capability-acquisition",
  createCapabilityAcquisitionSuite({
    apiBaseFor,
    apiRequest,
    cleanupConversations,
    loginViaUi,
    screenshot,
    applyBootstrapAdminCredentials,
  })
);

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.url) {
    console.error("Missing required --url");
    process.exit(2);
  }

  const { chromium } = loadPlaywright();
  const runId = nowStamp();
  const reportDir = path.join(args.reportDir, `${args.suite}-${runId}`);
  ensureDir(reportDir);

  const jsonPath = path.join(reportDir, "report.json");
  const markdownPath = path.join(reportDir, "report.md");

  const consoleErrors = [];
  const pageErrors = [];
  const requestFailures = [];
  const ignoredRequestFailures = [];
  const responses429 = [];

  const browser = await chromium.launch({
    channel: args.browser,
    headless: !args.headed,
  });

  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
  });

  page.on("console", (msg) => {
    const text = msg.text();
    if (msg.type() === "error" && !text.includes("_next/webpack-hmr")) {
      consoleErrors.push(text);
    }
  });
  page.on("pageerror", (error) => {
    pageErrors.push(String(error));
  });
  page.on("requestfailed", (request) => {
    const url = request.url();
    if (url.includes("_next/webpack-hmr")) return;
    if (url.includes("/_next/static/")) return;
    const failure = {
      url,
      errorText: request.failure() ? request.failure().errorText : "unknown",
    };
    if (isIgnorableRequestFailure(failure.url, failure.errorText)) {
      ignoredRequestFailures.push(failure);
      return;
    }
    requestFailures.push(failure);
  });
  page.on("response", (response) => {
    if (response.status() === 429) {
      responses429.push(response.url());
    }
  });

  let suiteResult;
  let suiteError = null;
  try {
    suiteResult = await getSuite(args.suite)(page, args, reportDir);
  } catch (error) {
    suiteError = String(error && error.stack ? error.stack : error);
    const failureScreenshot = await screenshot(page, reportDir, "failure.png");
    suiteResult = suiteResult || {
      steps: error.qaSteps || [],
      screenshots: error.qaScreenshots || [],
    };
    suiteResult.screenshots = [
      ...(suiteResult.screenshots || []),
      failureScreenshot,
    ];
  }

  const title = await page.title().catch(() => "");
  const currentUrl = page.url();
  const steps = suiteResult.steps || [];
  const stepsOk = steps.every((step) => step.ok);

  const report = {
    runId,
    suite: args.suite,
    url: args.url,
    currentUrl,
    title,
    browser: args.browser,
    headed: args.headed,
    ok:
      !suiteError &&
      stepsOk &&
      consoleErrors.length === 0 &&
      pageErrors.length === 0 &&
      requestFailures.length === 0 &&
      responses429.length === 0,
    suiteError,
    steps,
    consoleErrors,
    pageErrors,
    requestFailures,
    ignoredRequestFailures,
    responses429,
    screenshots: suiteResult.screenshots || [],
    reportDir,
    generatedAt: new Date().toISOString(),
  };

  fs.writeFileSync(jsonPath, JSON.stringify(report, null, 2), "utf8");

  const md = [
    "# Local Browser QA Report",
    "",
    `- Run ID: \`${runId}\``,
    `- Suite: \`${args.suite}\``,
    `- URL: \`${args.url}\``,
    `- Final URL: \`${currentUrl}\``,
    `- Browser: \`${args.browser}\``,
    `- Mode: \`${args.headed ? "headed" : "headless"}\``,
    `- OK: \`${report.ok}\``,
    "",
    "## Steps",
    "",
    ...steps.map((step) => `- ${step.ok ? "PASS" : "FAIL"} ${step.name}`),
    "",
    "## Signals",
    "",
    `- Console errors: ${consoleErrors.length}`,
    `- Page errors: ${pageErrors.length}`,
    `- Request failures: ${requestFailures.length}`,
    `- Ignored request failures: ${ignoredRequestFailures.length}`,
    `- 429 responses: ${responses429.length}`,
    "",
    "## Artifacts",
    "",
    `- JSON report: \`${jsonPath}\``,
    ...report.screenshots.map((file) => `- Screenshot: \`${file}\``),
  ];

  if (suiteError) {
    md.push("", "## Suite Error", "", "```", suiteError, "```");
  }
  if (consoleErrors.length) {
    md.push("", "## Console Errors", "", "```", ...consoleErrors, "```");
  }
  if (pageErrors.length) {
    md.push("", "## Page Errors", "", "```", ...pageErrors, "```");
  }
  if (requestFailures.length) {
    md.push("", "## Request Failures", "", "```json", JSON.stringify(requestFailures, null, 2), "```");
  }
  if (ignoredRequestFailures.length) {
    md.push("", "## Ignored Request Failures", "", "```json", JSON.stringify(ignoredRequestFailures, null, 2), "```");
  }
  if (responses429.length) {
    md.push("", "## 429 Responses", "", "```json", JSON.stringify(responses429, null, 2), "```");
  }

  fs.writeFileSync(markdownPath, `${md.join("\n")}\n`, "utf8");

  console.log(JSON.stringify(report, null, 2));

  if (args.keepOpen && args.headed) {
    console.error("Browser left open because --keep-open was set. Press Ctrl+C in this terminal when done.");
    await new Promise(() => {});
  }

  await browser.close();
  process.exit(report.ok ? 0 : 1);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
