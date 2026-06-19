const http = require("http");

async function startCapabilityMockServer(prefix, readRequestBody) {
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
        const inputs = Array.isArray(body.input) ? body.input : [body.input || ""];
        response.writeHead(200, { "content-type": "application/json" });
        response.end(
          JSON.stringify({
            object: "list",
            data: inputs.map((input, index) => ({
              object: "embedding",
              index,
              embedding: embeddingFor(prefix, String(input || "")),
            })),
            model: body.model || "embedding-3",
          })
        );
        return;
      }

      if (request.url.endsWith("/chat/completions")) {
        const messages = Array.isArray(body.messages) ? body.messages : [];
        const systemText = String(messages[0]?.content || "");
        const joined = messages.map((message) => String(message?.content || "")).join("\n");
        const lower = joined.toLowerCase();

        if (systemText.includes("Analyze the completed chat run")) {
          writeTextStream(response, body, analyzerJson(prefix));
          return;
        }

        if (
          systemText.includes("You are executing an activated Chainless Worker") &&
          systemText.includes(`${prefix}-fail-worker`)
        ) {
          response.writeHead(500, { "content-type": "application/json" });
          response.end(JSON.stringify({ error: `forced worker failure ${prefix}` }));
          return;
        }

        if (systemText.includes(`${prefix}-confirm-worker`)) {
          writeToolCallStream(response, body, {
            id: `call-confirm-${prefix}`,
            name: "shell_exec",
            args: { command: `printf 'worker-confirm-ok:${prefix}'` },
          });
          return;
        }

        if (lower.includes(`worker-confirm-ok:${prefix}`)) {
          writeTextStream(response, body, `worker-confirm-resume-ok:${prefix}`);
          return;
        }

        if (systemText.includes(`${prefix}-run-worker`)) {
          writeTextStream(response, body, `worker-auto-run-ok:${prefix}`);
          return;
        }

        if (lower.includes(`${prefix}-fail-worker`) || lower.includes("rescue failed worker")) {
          writeTextStream(response, body, `worker-fallback-ok:${prefix}`);
          return;
        }

        if (lower.includes("delete") && lower.includes(`${prefix}-run-worker`)) {
          writeTextStream(
            response,
            body,
            `delete-confirmation-required:${prefix}. Please confirm before any Worker is deleted.`
          );
          return;
        }

        if (lower.includes("recall") || lower.includes("remembered")) {
          writeTextStream(response, body, `memory-recall-ok:${prefix}`);
          return;
        }

        if (lower.includes(`${prefix}-skill-trigger`)) {
          writeTextStream(response, body, `skill-method-ok:${prefix}`);
          return;
        }

        writeTextStream(response, body, `capability-chat-ok:${prefix}`);
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

function embeddingFor(prefix, text) {
  const lower = text.toLowerCase();
  let head;
  if (lower.includes(`${prefix}-fail-worker`) || lower.includes("rescue failed worker")) {
    head = [0, 1, 0, 0, 0, 0, 0, 0];
    return padEmbedding(head);
  }
  if (
    lower.includes(`${prefix}-run-worker`) ||
    lower.includes("semantic equivalent request") ||
    lower.includes("same meaning")
  ) {
    head = [1, 0, 0, 0, 0, 0, 0, 0];
    return padEmbedding(head);
  }
  if (lower.includes(`${prefix}`)) {
    head = [0.8, 0.1, 0, 0, 0, 0, 0, 0];
    return padEmbedding(head);
  }
  return padEmbedding([0, 0, 1, 0, 0, 0, 0, 0]);
}

function padEmbedding(head) {
  return [...head, ...Array(Math.max(0, 1536 - head.length)).fill(0)];
}

function writeTextStream(response, body, content) {
  response.writeHead(200, {
    "content-type": "text/event-stream",
    "cache-control": "no-cache",
    connection: "keep-alive",
  });
  const base = {
    id: "chatcmpl-chainless-capability",
    object: "chat.completion.chunk",
    created: Math.floor(Date.now() / 1000),
    model: body.model || "w8-capability-mock",
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
}

function writeToolCallStream(response, body, { id, name, args }) {
  response.writeHead(200, {
    "content-type": "text/event-stream",
    "cache-control": "no-cache",
    connection: "keep-alive",
  });
  const base = {
    id: "chatcmpl-chainless-capability-tool",
    object: "chat.completion.chunk",
    created: Math.floor(Date.now() / 1000),
    model: body.model || "w8-capability-mock",
  };
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
                id,
                type: "function",
                function: {
                  name,
                  arguments: JSON.stringify(args),
                },
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
}

function analyzerJson(prefix) {
  return JSON.stringify({
    candidates: [
      {
        type: "memory",
        title: `${prefix}-memory`,
        body: `Remember ${prefix} browser QA preference.`,
        dedupe_key: `memory:${prefix}`,
        confidence: 0.94,
        source_evidence: [`User asked to remember ${prefix}.`],
        payload: {
          name: `${prefix}-memory`,
          memory_type: "project",
          memory_text: `Always cite ${prefix} when browser QA asks for remembered context.`,
          tags: [prefix, "browser-qa"],
        },
      },
      {
        type: "skill",
        title: `${prefix}-skill`,
        body: `Reusable method for ${prefix}.`,
        dedupe_key: `skill:${prefix}`,
        confidence: 0.91,
        source_evidence: [`User asked for a next-time method for ${prefix}.`],
        payload: {
          name: `${prefix}-skill`,
          description: `Use the ${prefix} skill method.`,
          trigger_terms: [`${prefix}-skill-trigger`],
        },
      },
      {
        type: "worker",
        title: `${prefix}-run-worker`,
        body: `Worker candidate for ${prefix}.`,
        dedupe_key: `worker:${prefix}`,
        confidence: 0.89,
        source_evidence: [`User asked to always run ${prefix}.`],
        payload: {
          name: `${prefix}-run-worker`,
          description: `Executes the ${prefix} semantic equivalent request.`,
          trigger: {
            keywords: [`${prefix}-run-worker`],
            examples: [`semantic equivalent request for ${prefix}`],
          },
          policy: { allowed_tools: [], risk: "low" },
          definition: {
            instructions: `Return worker-auto-run-ok:${prefix}.`,
            description: `Handle same meaning requests for ${prefix}.`,
          },
          verification_plan: { browser_qa: prefix },
        },
      },
    ],
  });
}

function createCapabilityLayerSuite({
  apiBaseFor,
  apiRequest,
  cleanupConversations,
  safeApiCall,
  loginViaUi,
  screenshot,
  applyBootstrapAdminCredentials,
  readRequestBody,
}) {
  return async function runCapabilityLayer(page, args, reportDir) {
    const apiBase = apiBaseFor(args.url, args.apiUrl);
    const steps = [];
    const screenshots = [];
    const stamp = Date.now();
    const prefix = `qa-v2-capability-${stamp}`;
    const providerName = `${prefix}-provider`;
    const createdConversationIds = [];
    const artifacts = {
      prefixes: [prefix],
      memoryIds: [],
      skillIds: [],
      workerIds: [],
      candidateIds: [],
    };
    let token = "";
    let mockProvider = null;
    let previousDefaultProviderName = null;

    try {
      applyBootstrapAdminCredentials(args);
      mockProvider = await startCapabilityMockServer(prefix, readRequestBody);
      token = await loginViaUi(page, args);
      if (!token) throw new Error("Login did not store a token");
      steps.push({ name: "auth-login", ok: true, tenant: args.tenant, username: args.username });
      previousDefaultProviderName = await readDefaultProviderName(apiBase, token, apiRequest);

      await apiRequest(
        apiBase,
        "/api/v1/llm-providers/",
        {
          method: "POST",
          body: JSON.stringify({
            name: providerName,
            api_base: mockProvider.baseUrl,
            api_key: `sk-${prefix}`,
            model: "w8-capability-mock",
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

      await apiRequest(
        apiBase,
        `/api/v1/conversations/${conversationId}`,
        { method: "PATCH", body: JSON.stringify({ title: `${prefix}-primary` }) },
        token
      );
      await page.reload({ waitUntil: "domcontentloaded", timeout: args.timeoutMs });
      await page.getByText(`${prefix}-primary`, { exact: true }).first().waitFor({ timeout: args.timeoutMs });
      steps.push({ name: "sidebar-rename-visible", ok: true });

      const input = page.getByTestId("chat-input");
      await input.fill(
        `Remember ${prefix}. Next time use ${prefix}-skill-trigger. Always create ${prefix}-run-worker.`
      );
      await page.keyboard.press("Control+Enter");
      await page.getByText(prefix, { exact: false }).last().waitFor({ timeout: 90000 });
      await page.getByTitle("Toggle preview").click();
      await page.getByRole("button", { name: "Inbox" }).click();
      await page.getByTestId("capability-inbox-panel").waitFor({ timeout: args.timeoutMs });
      await waitForCandidates(apiBase, token, prefix, ["memory", "skill", "worker"], args.timeoutMs);
      await page.getByText(`${prefix}-memory`, { exact: false }).first().waitFor({ timeout: args.timeoutMs });
      await page.getByText(`${prefix}-skill`, { exact: false }).first().waitFor({ timeout: args.timeoutMs });
      await page.getByText(`${prefix}-run-worker`, { exact: false }).first().waitFor({ timeout: args.timeoutMs });
      const inboxEvidence = await readElementEvidence(page, '[data-testid="capability-inbox-panel"]');
      steps.push({ name: "right-panel-inbox-candidates", ok: inboxEvidence.hasZincShell, evidence: inboxEvidence });
      screenshots.push(await screenshot(page, reportDir, "01-capability-inbox.png"));

      const candidates = await waitForCandidates(apiBase, token, prefix, ["memory", "skill", "worker"], args.timeoutMs);
      for (const candidate of candidates) {
        artifacts.candidateIds.push(candidate.id);
      }
      const memoryCandidate = candidates.find((candidate) => candidate.candidate_type === "memory");
      const skillCandidate = candidates.find((candidate) => candidate.candidate_type === "skill");
      const workerCandidate = candidates.find((candidate) => candidate.candidate_type === "worker");
      if (!memoryCandidate || !skillCandidate || !workerCandidate) {
        throw new Error(`Missing candidate types: ${JSON.stringify(candidates.map((item) => item.candidate_type))}`);
      }

      const acceptedMemory = await acceptCandidate(apiBase, token, memoryCandidate.id);
      artifacts.memoryIds.push(acceptedMemory.metadata?.target?.memory_id);
      const acceptedSkill = await acceptCandidate(apiBase, token, skillCandidate.id);
      artifacts.skillIds.push(acceptedSkill.metadata?.target?.skill_id);
      const acceptedWorker = await acceptCandidate(apiBase, token, workerCandidate.id);
      const workerId = acceptedWorker.metadata?.target?.worker_id;
      const versionId = acceptedWorker.metadata?.target?.worker_version_id;
      artifacts.workerIds.push(workerId);
      steps.push({
        name: "accept-memory-skill-worker-candidates",
        ok: Boolean(artifacts.memoryIds[0] && artifacts.skillIds[0] && workerId && versionId),
        memoryId: artifacts.memoryIds[0],
        skillId: artifacts.skillIds[0],
        workerId,
        versionId,
      });

      const memoryMerge = await apiRequest(
        apiBase,
        "/api/v1/memories/merge",
        { method: "POST", body: JSON.stringify({ task: `recall ${prefix}` }) },
        token
      );
      steps.push({
        name: "accepted-memory-later-recall",
        ok: String(memoryMerge.context || "").includes(prefix),
        memoryNames: (memoryMerge.memories || []).map((item) => item.name),
      });

      const skillMatch = await apiRequest(
        apiBase,
        "/api/v1/skills/match",
        { method: "POST", body: JSON.stringify({ text: `Run ${prefix}-skill-trigger now.` }) },
        token
      );
      steps.push({
        name: "accepted-skill-method-match",
        ok: (skillMatch.items || []).some((item) => item.skill?.id === artifacts.skillIds[0]),
        matched: skillMatch.items || [],
      });

      const directActivation = await expectApiError(
        apiBase,
        `/api/v1/workers/${encodeURIComponent(workerId)}/activate`,
        {
          method: "POST",
          body: JSON.stringify({
            version_id: versionId,
            activation_token: "not-issued",
            confirmation_evidence: { source: "w8-browser-qa" },
          }),
        },
        token
      );
      const verifyVersion = await apiRequest(
        apiBase,
        `/api/v1/workers/${encodeURIComponent(workerId)}/versions/${encodeURIComponent(versionId)}/verify`,
        {
          method: "POST",
          body: JSON.stringify({ verification_evidence: { command: "browser-qa", prefix } }),
        },
        token
      );
      const activationRequest = await apiRequest(
        apiBase,
        `/api/v1/workers/${encodeURIComponent(workerId)}/request-activation`,
        { method: "POST", body: JSON.stringify({ version_id: versionId }) },
        token
      );
      const activationNoEvidence = await expectApiError(
        apiBase,
        `/api/v1/workers/${encodeURIComponent(workerId)}/activate`,
        {
          method: "POST",
          body: JSON.stringify({
            version_id: versionId,
            activation_token: activationRequest.activation_token,
          }),
        },
        token
      );
      const activatedWorker = await apiRequest(
        apiBase,
        `/api/v1/workers/${encodeURIComponent(workerId)}/activate`,
        {
          method: "POST",
          body: JSON.stringify({
            version_id: versionId,
            activation_token: activationRequest.activation_token,
            confirmation_evidence: { source: "w8-browser-qa", prefix },
          }),
        },
        token
      );
      steps.push({
        name: "worker-verify-confirm-activate-audit",
        ok:
          directActivation.status === 409 &&
          activationNoEvidence.status === 422 &&
          verifyVersion.status === "verified" &&
          activationRequest.requires_confirmation === true &&
          activatedWorker.status === "active" &&
          activatedWorker.enabled === true &&
          activatedWorker.activation_evidence?.prefix === prefix,
        directActivation,
        activationNoEvidence,
        verifyVersionId: verifyVersion.id,
      });

      const semanticMatch = await apiRequest(
        apiBase,
        "/api/v1/workers/match",
        {
          method: "POST",
          body: JSON.stringify({
            request: `same meaning semantic equivalent request for ${prefix}`,
            input_payload: { request: `same meaning semantic equivalent request for ${prefix}` },
          }),
        },
        token
      );
      steps.push({
        name: "worker-semantic-match",
        ok: (semanticMatch.items || []).some(
          (item) => item.worker_id === workerId && ["auto_notice", "skip_and_suggest_after"].includes(item.decision)
        ),
        semanticMatch,
      });

      await input.fill(`same meaning semantic equivalent request for ${prefix}`);
      await page.keyboard.press("Control+Enter");
      await page.getByText(`Worker '${prefix}-run-worker' matched this request`, { exact: false }).first().waitFor({
        timeout: 90000,
      });
      await page.getByText(`worker-auto-run-ok:${prefix}`, { exact: false }).first().waitFor({ timeout: 90000 });
      await page.getByRole("button", { name: "Inbox" }).click();
      await page.getByTestId("worker-run-card").first().waitFor({ timeout: args.timeoutMs });
      steps.push({ name: "worker-auto-match-visible-notice", ok: true });
      screenshots.push(await screenshot(page, reportDir, "02-worker-auto-notice.png"));

      const disabledWorker = await apiRequest(
        apiBase,
        `/api/v1/workers/${encodeURIComponent(workerId)}/disable`,
        { method: "POST" },
        token
      );
      const disabledMatch = await apiRequest(
        apiBase,
        "/api/v1/workers/match",
        {
          method: "POST",
          body: JSON.stringify({
            request: `same meaning semantic equivalent request for ${prefix}`,
            input_payload: { request: `same meaning semantic equivalent request for ${prefix}` },
          }),
        },
        token
      );
      steps.push({
        name: "disable-worker-no-auto-match",
        ok: disabledWorker.enabled === false && !(disabledMatch.items || []).some((item) => item.worker_id === workerId),
      });
      await apiRequest(apiBase, `/api/v1/workers/${encodeURIComponent(workerId)}/enable`, { method: "POST" }, token);

      const deletePromptBefore = await apiRequest(apiBase, `/api/v1/workers/${encodeURIComponent(workerId)}`, {}, token);
      await input.fill(`delete ${prefix}-run-worker Worker`);
      await page.keyboard.press("Control+Enter");
      await page.getByText("Confirmation required", { exact: true }).first().waitFor({ timeout: args.timeoutMs });
      await page.getByText("worker_delete", { exact: false }).first().waitFor({ timeout: args.timeoutMs });
      const deletePromptAfter = await apiRequest(apiBase, `/api/v1/workers/${encodeURIComponent(workerId)}`, {}, token);
      steps.push({
        name: "natural-language-delete-confirmation-does-not-soft-delete",
        ok: deletePromptBefore.status === "active" && deletePromptAfter.status === "active",
        confirmation: "worker_delete",
      });
      await page.getByRole("button", { name: "Deny" }).click();
      await page.getByText("Confirmation required", { exact: true }).first().waitFor({
        state: "hidden",
        timeout: args.timeoutMs,
      });

      const failWorker = await createActivatedWorker(apiBase, token, {
        prefix,
        name: `${prefix}-fail-worker`,
        description: `Rescue failed worker for ${prefix}.`,
        trigger: { keywords: [`${prefix}-fail-worker`], examples: [`rescue failed worker ${prefix}`] },
        definition: { instructions: `Fail once then fallback for ${prefix}.` },
        policy: { allowed_tools: [], risk: "low" },
      });
      artifacts.workerIds.push(failWorker.worker.id);
      await input.fill(`rescue failed worker ${prefix}`);
      await page.keyboard.press("Control+Enter");
      await page.getByText(`Worker '${prefix}-fail-worker' failed; continuing`, { exact: false }).first().waitFor({
        timeout: 90000,
      });
      await page.getByText(`worker-fallback-ok:${prefix}`, { exact: false }).first().waitFor({ timeout: 90000 });
      const improvementCandidates = await waitForCandidates(apiBase, token, prefix, ["worker"], args.timeoutMs);
      const improvement = improvementCandidates.find(
        (candidate) => candidate.worker_id === failWorker.worker.id && candidate.title.includes("Improve Worker")
      );
      if (improvement) artifacts.candidateIds.push(improvement.id);
      steps.push({
        name: "worker-failure-fallback-improvement-candidate",
        ok: Boolean(improvement),
        improvementId: improvement?.id,
      });

      const blockedWorker = await createActivatedWorker(apiBase, token, {
        prefix,
        name: `${prefix}-blocked-worker`,
        description: `Blocked disallowed tool worker for ${prefix}.`,
        trigger: { keywords: [`${prefix}-blocked-worker`], examples: [`blocked shell worker ${prefix}`] },
        definition: { instructions: "Attempt shell_exec, which is not in allowed_tools." },
        policy: { allowed_tools: [], risk: "low" },
      });
      artifacts.workerIds.push(blockedWorker.worker.id);
      const blockedMatch = await apiRequest(
        apiBase,
        "/api/v1/workers/match",
        {
          method: "POST",
          body: JSON.stringify({
            request: `blocked shell worker ${prefix}`,
            input_payload: { request: `blocked shell worker ${prefix}` },
          }),
        },
        token
      );
      steps.push({
        name: "disallowed-tool-policy-denial",
        ok: (blockedMatch.items || []).some((item) => item.worker_id === blockedWorker.worker.id),
        coverage:
          "Backend policy denies tools outside allowed_tools before execution and on confirmation resume; W8 eval/backend tests cover the exact negative confirmation-resume branch.",
      });

      const confirmWorker = await createActivatedWorker(apiBase, token, {
        prefix,
        name: `${prefix}-confirm-worker`,
        description: `Confirmed shell worker for ${prefix}.`,
        trigger: { keywords: [`${prefix}-confirm-worker`], examples: [`run ${prefix}-confirm-worker now`] },
        definition: { instructions: "Call shell_exec once so confirmation resume can be verified." },
        policy: { allowed_tools: ["shell_exec"], risk: "low" },
      });
      artifacts.workerIds.push(confirmWorker.worker.id);
      await input.fill(`run ${prefix}-confirm-worker now`);
      await page.keyboard.press("Control+Enter");
      await page.getByText("Confirmation required", { exact: true }).first().waitFor({ timeout: args.timeoutMs });
      await page.getByText("shell_exec", { exact: false }).first().waitFor({ timeout: args.timeoutMs });
      await page.getByRole("button", { name: "Approve" }).click();
      await page.getByText(`worker-confirm-ok:${prefix}`, { exact: false }).first().waitFor({ timeout: 90000 });
      await page.getByText(`worker-confirm-resume-ok:${prefix}`, { exact: false }).first().waitFor({ timeout: 90000 });
      steps.push({
        name: "worker-confirmation-resume-policy-gate",
        ok: true,
        workerId: confirmWorker.worker.id,
      });

      await page.goto(args.url.replace(/\/$/, "") + "/settings", {
        waitUntil: "domcontentloaded",
        timeout: args.timeoutMs,
      });
      await page.getByRole("button", { name: "Capabilities", exact: true }).click();
      await page.getByText("Capability Inbox", { exact: true }).first().waitFor({ timeout: args.timeoutMs });
      await page.getByText(`${prefix}-memory`, { exact: false }).first().waitFor({ timeout: args.timeoutMs });
      const settingsCapabilityEvidence = await readSettingsEvidence(page);
      steps.push({
        name: "settings-capability-page-style-evidence",
        ok: settingsCapabilityEvidence.buttonLike && settingsCapabilityEvidence.cardLike,
        evidence: settingsCapabilityEvidence,
      });
      await page.getByRole("button", { name: "Workers", exact: true }).click();
      await page.getByTestId("worker-management-card").first().waitFor({ timeout: args.timeoutMs });
      await page.getByText(`${prefix}-run-worker`, { exact: false }).first().waitFor({ timeout: args.timeoutMs });
      screenshots.push(await screenshot(page, reportDir, "03-settings-capability-workers.png"));

      await page.getByText(`${prefix}-primary`, { exact: true }).first().click();
      await page.waitForURL(/\/chat$/, { timeout: args.timeoutMs });
      steps.push({ name: "settings-sidebar-conversation-navigates-chat", ok: true });

      for (let index = 0; index < 24; index += 1) {
        await apiRequest(
          apiBase,
          `/api/v1/conversations/${conversationId}/chat`,
          { method: "POST", body: JSON.stringify({ content: `scroll filler ${index} ${prefix}` }) },
          token
        );
      }
      await page.reload({ waitUntil: "domcontentloaded", timeout: args.timeoutMs });
      const scrollEvidence = await scrollChatViewport(page);
      steps.push({ name: "chat-scroll-style-evidence", ok: scrollEvidence.moved, evidence: scrollEvidence });

      await input.fill(`delete ${failWorker.worker.name} Worker`);
      await page.keyboard.press("Control+Enter");
      await page.getByText("Confirmation required", { exact: true }).first().waitFor({ timeout: args.timeoutMs });
      await page.getByText(failWorker.worker.id, { exact: false }).first().waitFor({ timeout: args.timeoutMs });
      await page.getByRole("button", { name: "Approve" }).click();
      const softDeleted = await waitForWorkerMissing(apiBase, token, failWorker.worker.id, args.timeoutMs);
      steps.push({
        name: "soft-delete-worker-with-confirmation",
        ok: softDeleted.status === 404,
        workerId: failWorker.worker.id,
        softDeleted,
      });

      const archiveId = await createConversationApi(apiBase, token, `${prefix}-archive-target`);
      createdConversationIds.push(archiveId);
      await page.reload({ waitUntil: "domcontentloaded", timeout: args.timeoutMs });
      await page.getByText(`${prefix}-archive-target`, { exact: true }).first().click();
      await page.waitForFunction(
        (id) => window.localStorage.getItem("activeConversationId") === id,
        archiveId,
        { timeout: args.timeoutMs }
      );
      page.once("dialog", async (dialog) => {
        if (!dialog.message().includes(`${prefix}-archive-target`)) {
          throw new Error(`Unexpected archive dialog: ${dialog.message()}`);
        }
        await dialog.accept();
      });
      await page.getByLabel("Archive conversation").first().click({ force: true });
      await page.getByText(`${prefix}-archive-target`, { exact: true }).waitFor({
        state: "hidden",
        timeout: args.timeoutMs,
      });
      createdConversationIds.splice(createdConversationIds.indexOf(archiveId), 1);
      steps.push({ name: "sidebar-select-delete-conversation", ok: true });
    } catch (error) {
      error.qaSteps = steps;
      error.qaScreenshots = screenshots;
      throw error;
    } finally {
      if (token) {
        const cleanup = await cleanupCapabilityArtifacts(
          apiBase,
          token,
          artifacts,
          createdConversationIds,
          providerName,
          previousDefaultProviderName,
          cleanupConversations,
          safeApiCall,
          apiRequest
        );
        steps.push({
          name: "cleanup-capability-artifacts",
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
  };
}

async function acceptCandidate(apiBase, token, candidateId) {
  return apiRequestNoImport(apiBase, `/api/v1/capability-candidates/${encodeURIComponent(candidateId)}/accept`, {
    method: "POST",
    body: JSON.stringify({}),
  }, token);
}

async function waitForCandidates(apiBase, token, prefix, requiredTypes, timeoutMs) {
  const deadline = Date.now() + Math.max(timeoutMs, 10000);
  let lastItems = [];
  while (Date.now() < deadline) {
    const page = await apiRequestNoImport(apiBase, "/api/v1/capability-candidates?limit=100", {}, token);
    lastItems = (page.items || []).filter(
      (candidate) =>
        String(candidate.title || "").includes(prefix) ||
        String(candidate.dedupe_key || "").includes(prefix) ||
        String(candidate.body || "").includes(prefix)
    );
    const types = new Set(lastItems.map((candidate) => candidate.candidate_type));
    if (requiredTypes.every((type) => types.has(type))) return lastItems;
    await sleep(700);
  }
  throw new Error(
    `Timed out waiting for capability candidates ${requiredTypes.join(", ")} with prefix ${prefix}; saw ${JSON.stringify(
      lastItems.map((candidate) => ({ id: candidate.id, type: candidate.candidate_type, title: candidate.title }))
    )}`
  );
}

async function createActivatedWorker(apiBase, token, { name, description, trigger, definition, policy }) {
  const worker = await apiRequestNoImport(
    apiBase,
    "/api/v1/workers",
    { method: "POST", body: JSON.stringify({ name, description, trigger, policy }) },
    token
  );
  const version = await apiRequestNoImport(
    apiBase,
    `/api/v1/workers/${encodeURIComponent(worker.id)}/versions`,
    {
      method: "POST",
      body: JSON.stringify({
        version: 1,
        definition,
        verification_plan: { browser_qa: true },
      }),
    },
    token
  );
  await apiRequestNoImport(
    apiBase,
    `/api/v1/workers/${encodeURIComponent(worker.id)}/versions/${encodeURIComponent(version.id)}/verify`,
    {
      method: "POST",
      body: JSON.stringify({ verification_evidence: { source: "w8-browser-qa" } }),
    },
    token
  );
  const activation = await apiRequestNoImport(
    apiBase,
    `/api/v1/workers/${encodeURIComponent(worker.id)}/request-activation`,
    { method: "POST", body: JSON.stringify({ version_id: version.id }) },
    token
  );
  const activated = await apiRequestNoImport(
    apiBase,
    `/api/v1/workers/${encodeURIComponent(worker.id)}/activate`,
    {
      method: "POST",
      body: JSON.stringify({
        version_id: version.id,
        activation_token: activation.activation_token,
        confirmation_evidence: { source: "w8-browser-qa" },
      }),
    },
    token
  );
  return { worker: activated, version };
}

async function createConversationApi(apiBase, token, title) {
  const conversation = await apiRequestNoImport(
    apiBase,
    "/api/v1/conversations/",
    { method: "POST", body: JSON.stringify({ title }) },
    token
  );
  return conversation.id;
}

async function waitForWorkerMissing(apiBase, token, workerId, timeoutMs) {
  const deadline = Date.now() + Math.max(timeoutMs, 10000);
  let last = null;
  while (Date.now() < deadline) {
    last = await expectApiError(apiBase, `/api/v1/workers/${encodeURIComponent(workerId)}`, {}, token);
    if (last.status === 404) return last;
    await sleep(500);
  }
  return last || { ok: false, status: 0, error: "worker visibility check did not run" };
}

async function expectApiError(apiBase, pathName, options, token) {
  try {
    await apiRequestNoImport(apiBase, pathName, options, token);
    return { ok: false, status: 200, error: "request unexpectedly succeeded" };
  } catch (error) {
    const text = String(error);
    const status = Number((text.match(/->\s+(\d+):/) || [])[1] || 0);
    const code = (text.match(/"code"\s*:\s*"([^"]+)"/) || [])[1] || "";
    return { ok: true, status, code, message: text };
  }
}

async function apiRequestNoImport(apiBase, pathName, options = {}, token = "") {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`${apiBase}${pathName}`, { ...options, headers });
  const text = await response.text();
  let body = {};
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { text };
  }
  if (!response.ok) {
    throw new Error(`${options.method || "GET"} ${pathName} -> ${response.status}: ${text}`);
  }
  return body;
}

async function readElementEvidence(page, selector) {
  return page.locator(selector).first().evaluate((node) => {
    const panel = node;
    const cards = [...panel.querySelectorAll('[data-testid="capability-hint-card"]')];
    return {
      className: panel.className,
      cardCount: cards.length,
      cardClasses: cards.slice(0, 3).map((card) => card.className),
      hasZincShell:
        String(panel.className).includes("space-y") &&
        cards.some((card) => String(card.className).includes("border-zinc-800")),
      text: panel.textContent?.slice(0, 500) || "",
    };
  });
}

  async function readSettingsEvidence(page) {
    return page.evaluate(() => {
      const buttons = [...document.querySelectorAll("button")].map((button) => ({
        text: button.textContent?.trim(),
        className: button.className,
      }));
      const cardNodes = [
        ...document.querySelectorAll(
          '[data-testid="capability-hint-card"], [data-testid="worker-management-card"], [class*="border-zinc-800"]'
        ),
      ];
      const cards = cardNodes.map((node) => String(node.className || ""));
      return {
        buttonLike: buttons.some(
          (button) =>
            button.text === "Capabilities" &&
            String(button.className).includes("bg-zinc-800") &&
            String(button.className).includes("text-zinc-100")
        ),
        cardLike: cards.some(
          (className) =>
            className.includes("border-zinc-800") &&
            (className.includes("bg-zinc-900") || className.includes("bg-zinc-950"))
        ),
        buttons: buttons.filter((button) => ["Capabilities", "Workers", "Settings"].includes(button.text || "")),
        cards: cards.slice(0, 12),
      };
    });
  }

async function scrollChatViewport(page) {
  await page.getByTestId("chat-scroll-viewport").waitFor({ timeout: 15000 });
  return page.getByTestId("chat-scroll-viewport").evaluate((node) => {
    const before = node.scrollTop;
    node.scrollTop = Math.max(0, node.scrollHeight - node.clientHeight);
    const after = node.scrollTop;
    return {
      before,
      after,
      moved: after > before,
      scrollHeight: node.scrollHeight,
      clientHeight: node.clientHeight,
      className: node.className,
    };
  });
}

async function cleanupCapabilityArtifacts(
  apiBase,
  token,
  artifacts,
  conversationIds,
  providerName,
  previousDefaultProviderName,
  cleanupConversations,
  safeApiCall,
  apiRequest
) {
  const results = [];
  if (conversationIds.length) {
    const cleanup = await cleanupConversations(apiBase, token, conversationIds);
    results.push({ label: "conversations", ok: cleanup.every((item) => item.ok), cleanup });
  }

  const workers = await safeApiCall("workers-list", () =>
    apiRequest(apiBase, "/api/v1/workers?limit=100", {}, token)
  );
  if (workers.ok) {
    for (const worker of workers.value?.items || []) {
      if (artifacts.prefixes.some((prefix) => String(worker.name || "").startsWith(prefix))) {
        results.push(
          await safeApiCall(`worker-delete-${worker.id}`, () =>
            apiRequest(apiBase, `/api/v1/workers/${encodeURIComponent(worker.id)}`, { method: "DELETE" }, token)
          )
        );
      }
    }
  }

  const memories = await safeApiCall("memories-list", () =>
    apiRequest(apiBase, "/api/v1/memories/?limit=100", {}, token)
  );
  if (memories.ok) {
    for (const memory of memories.value?.items || []) {
      if (artifacts.prefixes.some((prefix) => String(memory.name || "").startsWith(prefix))) {
        results.push(
          await safeApiCall(`memory-delete-${memory.id}`, () =>
            apiRequest(apiBase, `/api/v1/memories/${encodeURIComponent(memory.id)}`, { method: "DELETE" }, token)
          )
        );
      }
    }
  }

  const skills = await safeApiCall("skills-list", () =>
    apiRequest(apiBase, "/api/v1/skills/?limit=100", {}, token)
  );
  if (skills.ok) {
    for (const skill of skills.value?.items || []) {
      if (artifacts.prefixes.some((prefix) => String(skill.name || "").startsWith(prefix))) {
        results.push(
          await safeApiCall(`skill-delete-${skill.id}`, () =>
            apiRequest(apiBase, `/api/v1/skills/${encodeURIComponent(skill.id)}`, { method: "DELETE" }, token)
          )
        );
      }
    }
  }

  const candidates = await safeApiCall("candidates-list", () =>
    apiRequest(apiBase, "/api/v1/capability-candidates?limit=100", {}, token)
  );
  if (candidates.ok) {
    for (const candidate of candidates.value?.items || []) {
      const text = `${candidate.title || ""} ${candidate.body || ""} ${candidate.dedupe_key || ""}`;
      if (artifacts.prefixes.some((prefix) => text.includes(prefix)) && ["new", "seen", "snoozed"].includes(candidate.status)) {
        results.push(
          await safeApiCall(`candidate-archive-${candidate.id}`, () =>
            apiRequest(
              apiBase,
              `/api/v1/capability-candidates/${encodeURIComponent(candidate.id)}/archive`,
              { method: "POST" },
              token
            )
          )
        );
      }
    }
  }

  if (previousDefaultProviderName && previousDefaultProviderName !== providerName) {
    results.push(
      await safeApiCall("provider-restore-default", () =>
        apiRequest(
          apiBase,
          `/api/v1/llm-providers/${encodeURIComponent(previousDefaultProviderName)}/default`,
          { method: "POST" },
          token
        )
      )
    );
  }

  results.push(
    await safeApiCall("provider-delete", () =>
      apiRequest(apiBase, `/api/v1/llm-providers/${encodeURIComponent(providerName)}`, { method: "DELETE" }, token)
    )
  );
  return results;
}

async function readDefaultProviderName(apiBase, token, apiRequest) {
  const page = await apiRequest(apiBase, "/api/v1/llm-providers/?limit=100", {}, token);
  return (page.items || []).find((provider) => provider.is_default)?.name || null;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

module.exports = { createCapabilityLayerSuite };
