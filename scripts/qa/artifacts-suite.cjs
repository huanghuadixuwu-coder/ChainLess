const http = require("http");

async function startArtifactMockServer(prefix, artifactPath, artifactContent, readRequestBody) {
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
        const chatCallCount = calls.filter((call) => call.url.endsWith("/chat/completions")).length;
        response.writeHead(200, {
          "content-type": "text/event-stream",
          "cache-control": "no-cache",
          connection: "keep-alive",
        });
        const base = {
          id: "chatcmpl-chainless-artifacts",
          object: "chat.completion.chunk",
          created: Math.floor(Date.now() / 1000),
          model: body.model || "w6-artifact-mock",
        };

        if (chatCallCount === 1) {
          const args = JSON.stringify({
            path: artifactPath,
            content: artifactContent,
          });
          response.write(
            `data: ${JSON.stringify({
              ...base,
              choices: [
                {
                  index: 0,
                  delta: {
                    tool_calls: [
                      {
                        index: 0,
                        id: "call_w6_file_write",
                        type: "function",
                        function: { name: "file_write", arguments: "" },
                      },
                    ],
                  },
                  finish_reason: null,
                },
              ],
            })}\n\n`
          );
          response.write(
            `data: ${JSON.stringify({
              ...base,
              choices: [
                {
                  index: 0,
                  delta: {
                    tool_calls: [
                      {
                        index: 0,
                        function: { arguments: args },
                      },
                    ],
                  },
                  finish_reason: null,
                },
              ],
            })}\n\n`
          );
          response.write(
            `data: ${JSON.stringify({
              ...base,
              choices: [{ index: 0, delta: {}, finish_reason: "tool_calls" }],
            })}\n\n`
          );
          response.write("data: [DONE]\n\n");
          response.end();
          return;
        }

        const content = `artifact-flow-ok:${prefix}`;
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

function createArtifactsSuite({
  apiBaseFor,
  apiRequest,
  cleanupConversations,
  safeApiCall,
  loginViaUi,
  screenshot,
  applyBootstrapAdminCredentials,
  readRequestBody,
}) {
  return async function runArtifacts(page, args, reportDir) {
    const apiBase = apiBaseFor(args.url, args.apiUrl);
    const steps = [];
    const screenshots = [];
    const createdConversationIds = [];
    const stamp = Date.now();
    const prefix = `w6-artifacts-${stamp}`;
    const artifactPath = `w6/${prefix}.py`;
    const artifactContent = `print(6 * 7)\n# ${prefix}\n`;
    const providerName = `${prefix}-provider`;
    let token = "";
    let mockProvider = null;

    try {
      applyBootstrapAdminCredentials(args);
      mockProvider = await startArtifactMockServer(prefix, artifactPath, artifactContent, readRequestBody);
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
            model: "w6-artifact-mock",
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
      steps.push({ name: "conversation-create", ok: Boolean(conversationId), conversationId });

      const input = page.getByPlaceholder(/Type a message/);
      await input.fill(`Create the W6 artifact file ${artifactPath}.`);
      await page.keyboard.press("Control+Enter");
      await page.getByText("file_write", { exact: true }).waitFor({ timeout: 90000 });
      await page.getByText(`artifact-flow-ok:${prefix}`, { exact: false }).waitFor({ timeout: 90000 });
      steps.push({ name: "chat-file-write-tool", ok: true });

      await page.getByTitle("Toggle preview").click();
      await page.getByRole("button", { name: "Files" }).click();
      const fileList = page.getByTestId("artifact-file-list");
      await fileList.waitFor({ timeout: args.timeoutMs });
      await fileList
        .getByTestId("artifact-row")
        .filter({ hasText: artifactPath })
        .first()
        .waitFor({ timeout: args.timeoutMs });
      await page.getByTestId("artifact-content").getByText(prefix, { exact: false }).waitFor({
        timeout: args.timeoutMs,
      });
      steps.push({ name: "files-tab-real-artifact", ok: true });
      screenshots.push(await screenshot(page, reportDir, "01-files-artifact.png"));

      await page.getByRole("button", { name: "Diff" }).click();
      await page.getByTestId("artifact-diff").waitFor({ timeout: args.timeoutMs });
      await page.getByTestId("artifact-diff").getByText(`+print(6 * 7)`, { exact: false }).waitFor({
        timeout: args.timeoutMs,
      });
      steps.push({ name: "diff-tab-real-unified-diff", ok: true });
      screenshots.push(await screenshot(page, reportDir, "02-diff-artifact.png"));

      await page.reload({ waitUntil: "domcontentloaded", timeout: args.timeoutMs });
      await page.waitForLoadState("networkidle", { timeout: args.timeoutMs }).catch(() => {});
      await page.getByTitle("Toggle preview").click();
      await page.getByRole("button", { name: "Files" }).click();
      await page
        .getByTestId("artifact-file-list")
        .getByTestId("artifact-row")
        .filter({ hasText: artifactPath })
        .first()
        .waitFor({ timeout: args.timeoutMs });
      steps.push({ name: "reload-preserves-artifact-list", ok: true });

      const chatCalls = mockProvider.calls.filter((call) => call.url.endsWith("/chat/completions")).length;
      steps.push({ name: "mock-provider-observed-tool-loop", ok: chatCalls >= 2, chatCalls });
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
        await safeApiCall("provider-delete", () =>
          apiRequest(
            apiBase,
            `/api/v1/llm-providers/${encodeURIComponent(providerName)}`,
            { method: "DELETE" },
            token
          )
        );
      }
      await page.evaluate(() => window.localStorage.removeItem("activeConversationId")).catch(() => {});
      if (mockProvider) {
        await mockProvider.close().catch(() => {});
      }
    }

    return { steps, screenshots };
  };
}

module.exports = { createArtifactsSuite };
