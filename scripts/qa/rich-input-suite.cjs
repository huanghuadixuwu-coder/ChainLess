const fs = require("fs");
const http = require("http");
const path = require("path");

async function startRichInputMockServer(prefix, readRequestBody) {
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
        const content = [
          `rich-input-ok:${prefix}`,
          "",
          "```python",
          "print(6 * 7)",
          "```",
        ].join("\n");
        response.writeHead(200, {
          "content-type": "text/event-stream",
          "cache-control": "no-cache",
          connection: "keep-alive",
        });
        const base = {
          id: "chatcmpl-chainless-rich-input",
          object: "chat.completion.chunk",
          created: Math.floor(Date.now() / 1000),
          model: body.model || "w7-rich-input-mock",
        };
        response.write(
          `data: ${JSON.stringify({
            ...base,
            choices: [{ index: 0, delta: { content }, finish_reason: null }],
          })}\n\n`
        );
        response.write(
          `data: ${JSON.stringify({
            ...base,
            choices: [{ index: 0, delta: {}, finish_reason: "stop" }],
          })}\n\n`
        );
        response.write("data: [DONE]\n\n");
        response.end();
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

function createRichInputSuite({
  apiBaseFor,
  apiRequest,
  cleanupConversations,
  safeApiCall,
  loginViaUi,
  screenshot,
  applyBootstrapAdminCredentials,
  readRequestBody,
}) {
  return async function runRichInput(page, args, reportDir) {
    const apiBase = apiBaseFor(args.url, args.apiUrl);
    const steps = [];
    const screenshots = [];
    const createdConversationIds = [];
    const stamp = Date.now();
    const prefix = `w7-rich-${stamp}`;
    const providerName = `${prefix}-provider`;
    const uploadPath = path.join(reportDir, `${prefix}-notes.txt`);
    const uploadContent = `typed upload fact ${prefix}\n`;
    let token = "";
    let mockProvider = null;

    try {
      applyBootstrapAdminCredentials(args);
      mockProvider = await startRichInputMockServer(prefix, readRequestBody);
      fs.writeFileSync(uploadPath, uploadContent, "utf8");

      token = await loginViaUi(page, args);
      if (!token) throw new Error("Login did not store a token");
      steps.push({ name: "auth-login", ok: true });

      await apiRequest(
        apiBase,
        "/api/v1/llm-providers/",
        {
          method: "POST",
          body: JSON.stringify({
            name: providerName,
            api_base: mockProvider.baseUrl,
            api_key: `sk-${prefix}`,
            model: "w7-rich-input-mock",
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

      await page.goto(args.url.replace(/\/$/, "") + "/chat", {
        waitUntil: "domcontentloaded",
        timeout: args.timeoutMs,
      });
      await page.getByTestId("chat-input").waitFor({ timeout: args.timeoutMs });

      const beforeUnsafeShortcut = await page.evaluate(() =>
        window.localStorage.getItem("activeConversationId")
      );
      const pagesBeforeCtrlN = page.context().pages().length;
      await page.getByTestId("chat-input").focus();
      await page.keyboard.press("Control+N");
      await page.waitForTimeout(400);
      const afterUnsafeShortcut = await page.evaluate(() =>
        window.localStorage.getItem("activeConversationId")
      );
      steps.push({
        name: "ctrl-n-ignored-inside-input",
        ok:
          beforeUnsafeShortcut === afterUnsafeShortcut &&
          page.context().pages().length === pagesBeforeCtrlN,
      });

      await page.evaluate(() => {
        if (document.activeElement instanceof HTMLElement) {
          document.activeElement.blur();
        }
      });
      await page.keyboard.press("Control+N");
      await page.waitForFunction(() => Boolean(window.localStorage.getItem("activeConversationId")), null, {
        timeout: args.timeoutMs,
      });
      const firstConversationId = await page.evaluate(() =>
        window.localStorage.getItem("activeConversationId")
      );
      createdConversationIds.push(firstConversationId);
      steps.push({
        name: "ctrl-n-new-conversation",
        ok: Boolean(firstConversationId),
        conversationId: firstConversationId,
      });

      await page.getByTestId("chat-input").focus();
      await page.keyboard.press("Control+K");
      await page.waitForTimeout(400);
      const activeTagAfterCtrlK = await page.evaluate(
        () => document.activeElement?.tagName
      );
      steps.push({
        name: "ctrl-k-ignored-inside-input",
        ok:
          (await page.getByTestId("command-palette").count()) === 0 &&
          activeTagAfterCtrlK === "TEXTAREA",
      });

      await page.evaluate(() => {
        if (document.activeElement instanceof HTMLElement) {
          document.activeElement.blur();
        }
      });
      await page.keyboard.press("Control+K");
      await page.getByTestId("command-palette").waitFor({ timeout: args.timeoutMs });
      steps.push({ name: "ctrl-k-command-palette", ok: true });
      await page.keyboard.press("Enter");
      await page.waitForFunction(
        (previous) => window.localStorage.getItem("activeConversationId") !== previous,
        firstConversationId,
        { timeout: args.timeoutMs }
      );
      const conversationId = await page.evaluate(() =>
        window.localStorage.getItem("activeConversationId")
      );
      createdConversationIds.push(conversationId);
      steps.push({
        name: "command-palette-new-conversation",
        ok: Boolean(conversationId && conversationId !== firstConversationId),
        conversationId,
      });

      const input = page.getByTestId("chat-input");
      await input.fill("Use @code");
      await page.getByTestId("tool-picker").waitFor({ timeout: args.timeoutMs });
      await page
        .getByTestId("tool-option")
        .filter({ hasText: "@code_as_action" })
        .first()
        .waitFor({ timeout: args.timeoutMs });
      await page.keyboard.press("Enter");
      const toolValue = await input.inputValue();
      steps.push({
        name: "at-tool-picker-keyboard-selection",
        ok: toolValue.includes("@code_as_action "),
        value: toolValue,
      });

      await page.locator('input[type="file"]').setInputFiles(uploadPath);
      await page
        .getByTestId("attachment-chip")
        .filter({ hasText: `${prefix}-notes.txt` })
        .first()
        .waitFor({ timeout: args.timeoutMs });
      steps.push({ name: "file-picker-upload", ok: true });

      await page.evaluate((runPrefix) => {
        const dropzone = document.querySelector('[data-testid="file-dropzone"]');
        if (!dropzone) throw new Error("file dropzone not found");
        const dataTransfer = new DataTransfer();
        dataTransfer.items.add(
          new File([`drag upload fact ${runPrefix}\n`], `${runPrefix}-drag.txt`, {
            type: "text/plain",
          })
        );
        dropzone.dispatchEvent(
          new DragEvent("dragover", {
            bubbles: true,
            cancelable: true,
            dataTransfer,
          })
        );
        dropzone.dispatchEvent(
          new DragEvent("drop", {
            bubbles: true,
            cancelable: true,
            dataTransfer,
          })
        );
      }, prefix);
      await page
        .getByTestId("attachment-chip")
        .filter({ hasText: `${prefix}-drag.txt` })
        .first()
        .waitFor({ timeout: args.timeoutMs });
      steps.push({ name: "drag-drop-upload", ok: true });

      await input.fill(`Summarize the attached files for ${prefix}.`);
      await page.keyboard.press("Control+Enter");
      await page.getByText(`rich-input-ok:${prefix}`, { exact: false }).waitFor({
        timeout: 90000,
      });
      steps.push({ name: "chat-with-attachments", ok: true });

      const chatCall = mockProvider.calls.find((call) =>
        String(call.url || "").endsWith("/chat/completions")
      );
      const messagesText = JSON.stringify(chatCall?.body?.messages || []);
      steps.push({
        name: "backend-injected-upload-content",
        ok:
          messagesText.includes(`typed upload fact ${prefix}`) &&
          messagesText.includes(`drag upload fact ${prefix}`),
      });

      const foldButton = page.getByTestId("code-fold-button").first();
      await foldButton.waitFor({ timeout: args.timeoutMs });
      await foldButton.click();
      await page.getByText("print(6 * 7)", { exact: true }).waitFor({
        state: "hidden",
        timeout: args.timeoutMs,
      });
      await foldButton.click();
      await page.getByText("print(6 * 7)", { exact: true }).waitFor({
        timeout: args.timeoutMs,
      });
      steps.push({ name: "markdown-code-fold", ok: true });

      await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
      await page.getByTestId("code-copy-button").first().click();
      await page.getByText("Copied", { exact: true }).waitFor({
        timeout: args.timeoutMs,
      });
      steps.push({ name: "markdown-code-copy", ok: true });

      for (let index = 0; index < 16; index += 1) {
        await apiRequest(
          apiBase,
          `/api/v1/conversations/${conversationId}/chat`,
          {
            method: "POST",
            body: JSON.stringify({
              content: `Long virtual row ${index} for ${prefix}`,
            }),
          },
          token
        );
      }
      await page.reload({ waitUntil: "domcontentloaded", timeout: args.timeoutMs });
      await page.getByTestId("chat-input").waitFor({ timeout: args.timeoutMs });
      await page.waitForFunction(
        () => {
          const windowEl = document.querySelector(
            '[data-testid="virtual-message-window"]'
          );
          const total = Number(windowEl?.getAttribute("data-total-messages") || 0);
          const rendered = Number(
            windowEl?.getAttribute("data-rendered-messages") || 0
          );
          const rows = document.querySelectorAll('[data-testid="message-row"]').length;
          return total > 30 && rendered > 0 && rows > 0 && rendered < total;
        },
        null,
        { timeout: Math.min(args.timeoutMs, 15000) }
      ).catch(async (error) => {
        const virtualStats = await page.evaluate(readVirtualStats);
        throw new Error(
          `virtual window did not reduce rendered rows: ${JSON.stringify(
            virtualStats
          )}; ${error.message}`
        );
      });
      const virtualStats = await page.evaluate(readVirtualStats);
      steps.push({
        name: "long-conversation-virtual-window",
        ok:
          virtualStats.total > 30 &&
          virtualStats.rendered < virtualStats.total &&
          virtualStats.rows <= virtualStats.rendered &&
          virtualStats.scrollHeight > virtualStats.clientHeight,
        virtualStats,
      });
      screenshots.push(await screenshot(page, reportDir, "01-rich-input.png"));
    } catch (error) {
      error.qaSteps = steps;
      error.qaScreenshots = screenshots;
      throw error;
    } finally {
      if (token) {
        if (createdConversationIds.length) {
          const cleanup = await cleanupConversations(
            apiBase,
            token,
            createdConversationIds
          );
          steps.push({
            name: "cleanup-conversations",
            ok: cleanup.every((item) => item.ok),
            cleanup,
          });
        }
        await safeApiCall("provider-delete", () =>
          apiRequest(
            apiBase,
            `/api/v1/llm-providers/${encodeURIComponent(providerName)}`,
            { method: "DELETE" },
            token
          )
        );
      }
      await page
        .evaluate(() => window.localStorage.removeItem("activeConversationId"))
        .catch(() => {});
      if (mockProvider) {
        await mockProvider.close().catch(() => {});
      }
    }

    return { steps, screenshots };
  };
}

module.exports = {
  createRichInputSuite,
};

function readVirtualStats() {
  const windowEl = document.querySelector('[data-testid="virtual-message-window"]');
  const viewport = document.querySelector('[data-testid="chat-scroll-viewport"]');
  return {
    total: Number(windowEl?.getAttribute("data-total-messages") || 0),
    rendered: Number(windowEl?.getAttribute("data-rendered-messages") || 0),
    rows: document.querySelectorAll('[data-testid="message-row"]').length,
    scrollHeight: viewport?.scrollHeight || 0,
    clientHeight: viewport?.clientHeight || 0,
  };
}
