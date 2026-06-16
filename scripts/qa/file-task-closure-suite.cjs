const fs = require("fs");
const http = require("http");
const path = require("path");

async function startFileTaskClosureMockServer(prefix, readRequestBody) {
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
        response.writeHead(200, {
          "content-type": "text/event-stream",
          "cache-control": "no-cache",
          connection: "keep-alive",
        });
        const base = {
          id: "chatcmpl-chainless-file-task-closure",
          object: "chat.completion.chunk",
          created: Math.floor(Date.now() / 1000),
          model: body.model || "w12-file-task-mock",
        };
        const messages = Array.isArray(body.messages) ? body.messages : [];
        const lastMessage = messages[messages.length - 1] || {};
        const joinedMessages = messages
          .map((message) => String(message && message.content ? message.content : ""))
          .join("\n");
        const writeFrame = (payload) => {
          response.write(`data: ${JSON.stringify(payload)}\n\n`);
        };
        const finish = (reason = "stop") => {
          writeFrame({
            ...base,
            choices: [{ index: 0, delta: {}, finish_reason: reason }],
          });
          response.write("data: [DONE]\n\n");
          response.end();
        };
        const writeText = (content) => {
          writeFrame({
            ...base,
            choices: [{ index: 0, delta: { content }, finish_reason: null }],
          });
          finish("stop");
        };
        const writeTool = (callId, name, args) => {
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
          finish("tool_calls");
        };

        if (lastMessage.role === "tool" && String(lastMessage.content || "").includes("w12 uploaded phrase")) {
          writeTool(`call_${prefix}_write`, "file_write", {
            path: `w12-output-${prefix}.txt`,
            content: `w12 output phrase ${prefix}\nsource: ${lastMessage.content}`,
          });
          return;
        }

        if (lastMessage.role === "tool" && String(lastMessage.content || "").includes("Written")) {
          writeText(`file-task-closure-ok:${prefix}`);
          return;
        }

        const manifestMatch = joinedMessages.match(/input\/[0-9a-f-]{36}\/[A-Za-z0-9._-]+\.txt/);
        if (manifestMatch) {
          writeTool(`call_${prefix}_read`, "file_read", {
            path: manifestMatch[0],
          });
          return;
        }

        writeText(`file-task-closure-missing-manifest:${prefix}`);
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

function createFileTaskClosureSuite({
  apiBaseFor,
  apiRequest,
  cleanupConversations,
  safeApiCall,
  loginViaUi,
  screenshot,
  applyBootstrapAdminCredentials,
  readRequestBody,
}) {
  return async function runFileTaskClosure(page, args, reportDir) {
    const apiBase = apiBaseFor(args.url, args.apiUrl);
    const steps = [];
    const screenshots = [];
    const createdConversationIds = [];
    const stamp = Date.now();
    const prefix = `w12-file-${stamp}`;
    const providerName = `${prefix}-provider`;
    const conversationTitle = `${prefix}-conversation`;
    const uploadPath = path.join(reportDir, `${prefix}-input.txt`);
    const uploadContent = `w12 uploaded phrase ${prefix}\n`;
    const outputPath = `w12-output-${prefix}.txt`;
    let token = "";
    let mockProvider = null;

    try {
      applyBootstrapAdminCredentials(args);
      mockProvider = await startFileTaskClosureMockServer(prefix, readRequestBody);
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
            model: "w12-file-task-mock",
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
      await page.getByRole("button", { name: "New Chat" }).first().click();
      await page.waitForFunction(() => Boolean(window.localStorage.getItem("activeConversationId")), null, {
        timeout: args.timeoutMs,
      });
      const conversationId = await page.evaluate(() => window.localStorage.getItem("activeConversationId"));
      createdConversationIds.push(conversationId);
      await apiRequest(
        apiBase,
        `/api/v1/conversations/${conversationId}`,
        {
          method: "PATCH",
          body: JSON.stringify({ title: conversationTitle }),
        },
        token
      );
      steps.push({ name: "conversation-create", ok: Boolean(conversationId), conversationId });

      await page.locator('input[type="file"]').setInputFiles(uploadPath);
      await page
        .getByTestId("attachment-chip")
        .filter({ hasText: `${prefix}-input.txt` })
        .filter({ hasText: "available" })
        .first()
        .waitFor({ timeout: args.timeoutMs });
      steps.push({ name: "upload-state-available", ok: true });

      const input = page.getByTestId("chat-input");
      await input.fill("Read the uploaded file with file_read, then write a result file.");
      await page.keyboard.press("Control+Enter");
      await page
        .getByTestId("attachment-chip")
        .filter({ hasText: `${prefix}-input.txt` })
        .filter({ hasText: "sent" })
        .first()
        .waitFor({ timeout: args.timeoutMs });
      steps.push({ name: "sent-message-attachment-visible", ok: true });

      await page.getByText("file_read", { exact: true }).waitFor({ timeout: 90000 });
      steps.push({ name: "file-read-tool-used", ok: true });
      await page.getByText(`file-task-closure-ok:${prefix}`, { exact: false }).waitFor({ timeout: 90000 });

      await page.getByTitle("Toggle preview").click();
      await page.getByRole("button", { name: "Files" }).click();
      const outputRow = page
        .getByTestId("artifact-file-list")
        .getByTestId("artifact-row")
        .filter({ hasText: outputPath })
        .first();
      await outputRow.waitFor({ timeout: args.timeoutMs });
      steps.push({ name: "generated-artifact-visible", ok: true });
      screenshots.push(await screenshot(page, reportDir, "01-file-task-files.png"));

      const [download] = await Promise.all([
        page.waitForEvent("download", { timeout: args.timeoutMs }),
        outputRow.getByRole("button", { name: /Download/ }).click(),
      ]);
      const downloadedPath = path.join(reportDir, await download.suggestedFilename());
      await download.saveAs(downloadedPath);
      const downloaded = fs.readFileSync(downloadedPath, "utf8");
      steps.push({
        name: "artifact-download-bytes-match",
        ok:
          downloaded.includes(`w12 output phrase ${prefix}`) &&
          downloaded.includes(`w12 uploaded phrase ${prefix}`),
        downloadedPath,
      });

      await page.goto(args.url.replace(/\/$/, "") + "/settings", {
        waitUntil: "domcontentloaded",
        timeout: args.timeoutMs,
      });
      await page.getByText("Settings", { exact: true }).first().waitFor({ timeout: args.timeoutMs });
      await page.getByText(conversationTitle, { exact: true }).first().click();
      await page.waitForURL(/\/chat$/, { timeout: args.timeoutMs });
      steps.push({ name: "settings-sidebar-navigates-chat", ok: true });

      const chatCalls = mockProvider.calls.filter((call) => call.url.endsWith("/chat/completions")).length;
      steps.push({ name: "mock-provider-observed-file-tool-loop", ok: chatCalls >= 3, chatCalls });
    } catch (error) {
      error.qaSteps = steps;
      error.qaScreenshots = screenshots;
      throw error;
    } finally {
      if (token) {
        if (createdConversationIds.length) {
          const cleanup = await cleanupConversations(apiBase, token, createdConversationIds);
          steps.push({ name: "cleanup-conversations", ok: cleanup.every((item) => item.ok), cleanup });
        }
        const providerCleanup = await safeApiCall("provider-delete", () =>
          apiRequest(
            apiBase,
            `/api/v1/llm-providers/${encodeURIComponent(providerName)}`,
            { method: "DELETE" },
            token
          )
        );
        steps.push({ name: "cleanup-provider", ok: providerCleanup.ok, cleanup: providerCleanup });
      }
      await page.evaluate(() => window.localStorage.removeItem("activeConversationId")).catch(() => {});
      if (mockProvider) {
        await mockProvider.close().catch(() => {});
      }
    }

    return { steps, screenshots };
  };
}

module.exports = { createFileTaskClosureSuite };
