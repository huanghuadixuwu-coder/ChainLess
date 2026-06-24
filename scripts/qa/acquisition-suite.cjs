function createCapabilityAcquisitionSuite({
  apiBaseFor,
  apiRequest,
  cleanupConversations,
  loginViaUi,
  screenshot,
  applyBootstrapAdminCredentials,
}) {
  return async function runCapabilityAcquisition(page, args, reportDir) {
    const apiBase = apiBaseFor(args.url, args.apiUrl);
    const steps = [];
    const screenshots = [];
    const createdConversationIds = [];
    let token = "";

    try {
      applyBootstrapAdminCredentials(args);
      token = await loginViaUi(page, args);
      if (!token) throw new Error("Login did not store a token");
      steps.push({ name: "auth-login", ok: true, tenant: args.tenant, username: args.username });

      const overview = await readAcquisitionOverview(apiBase, token, apiRequest);
      steps.push({
        name: "acquisition-api-overview",
        ok: overview.enabled,
        enabled: overview.enabled,
        counts: overview.counts,
        unavailable: overview.unavailable,
      });

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

      const title = `qa-acquisition-${Date.now()}`;
      await apiRequest(
        apiBase,
        `/api/v1/conversations/${encodeURIComponent(conversationId)}`,
        { method: "PATCH", body: JSON.stringify({ title }) },
        token
      );
      await page.reload({ waitUntil: "domcontentloaded", timeout: args.timeoutMs });
      await page.getByText(title, { exact: true }).first().waitFor({ timeout: args.timeoutMs });

      const sidebarControls = await revealSidebarControls(page, title);
      steps.push({
        name: "sidebar-conversation-rename-delete-visible",
        ok: sidebarControls.renameVisible && sidebarControls.deleteVisible,
        sidebarControls,
      });

      const input = page.getByTestId("chat-input");
      await input.waitFor({ timeout: args.timeoutMs });
      await page.getByTitle("Toggle preview").click();
      const rightPanel = await readRightPanelAcquisitionSurface(page, args.timeoutMs);
      steps.push({
        name: "chat-right-panel-acquisition-presence",
        ok: rightPanel.present,
        rightPanel,
      });
      screenshots.push(await screenshot(page, reportDir, "01-chat-acquisition-panel.png"));

      const scrollEvidence = await verifyChatScrollContainer(page, args.timeoutMs);
      steps.push({ name: "chat-scroll-works", ok: scrollEvidence.moved, evidence: scrollEvidence });

      await page.goto(args.url.replace(/\/$/, "") + "/settings", {
        waitUntil: "domcontentloaded",
        timeout: args.timeoutMs,
      });
      await page.getByText("Settings", { exact: true }).first().waitFor({ timeout: args.timeoutMs });
      const settingsSurface = await openAcquisitionSettingsSurface(page, args.timeoutMs);
      steps.push({
        name: "settings-acquisition-section",
        ok: settingsSurface.present,
        settingsSurface,
      });

      const renderedAcquisition = await readRenderedAcquisitionEvidence(page);
      const expectedText = ["problem", "cause", "risk", "next", "recovery"];
      const textCoverage = expectedText.filter((needle) =>
        renderedAcquisition.text.toLowerCase().includes(needle)
      );
      steps.push({
        name: "acquisition-copy-or-empty-state",
        ok: overview.hasSeedData
          ? textCoverage.length >= 3
          : settingsSurface.emptyOrDisabled || renderedAcquisition.emptyOrDisabled,
        hasSeedData: overview.hasSeedData,
        textCoverage,
        emptyOrDisabled: settingsSurface.emptyOrDisabled || renderedAcquisition.emptyOrDisabled,
      });

      const controls = await readAcquisitionControls(page);
      steps.push({
        name: "approve-revoke-rollback-controls-when-available",
        ok:
          !overview.hasSeedData ||
          controls.approveExploration ||
          controls.approveActivation ||
          controls.rollback ||
          controls.revoke,
        controls,
        hasActivatedTargets: overview.hasActivatedTargets,
      });
      steps.push({
        name: "rollback-visible-for-activated-targets",
        ok: !overview.hasActivatedTargets || controls.rollback,
        hasActivatedTargets: overview.hasActivatedTargets,
        rollbackVisible: controls.rollback,
      });
      screenshots.push(await screenshot(page, reportDir, "02-settings-acquisition.png"));

      await page.getByText(title, { exact: true }).first().click();
      await page.waitForURL(/\/chat$/, { timeout: args.timeoutMs });
      steps.push({ name: "settings-conversation-click-routes-chat", ok: true });
    } catch (error) {
      error.qaSteps = steps;
      error.qaScreenshots = screenshots;
      throw error;
    } finally {
      if (token && createdConversationIds.length) {
        const cleanup = await cleanupConversations(apiBase, token, createdConversationIds);
        steps.push({ name: "cleanup-conversations", ok: cleanup.every((item) => item.ok), cleanup });
      }
      await page.evaluate(() => window.localStorage.removeItem("activeConversationId")).catch(() => {});
    }

    return { steps, screenshots };
  };
}

async function readAcquisitionOverview(apiBase, token, apiRequest) {
  const paths = {
    gaps: "/api/v1/acquisition/gaps?limit=100",
    explorations: "/api/v1/acquisition/explorations?limit=100",
    recommendations: "/api/v1/acquisition/recommendations?limit=100",
    proposals: "/api/v1/acquisition/proposals?limit=100",
    permissions: "/api/v1/acquisition/permissions?limit=100",
    credentials: "/api/v1/acquisition/credential-connections?limit=100",
    browserSessions: "/api/v1/acquisition/browser-sessions?limit=100",
    workspaceConnectors: "/api/v1/acquisition/workspace-connectors?limit=100",
  };
  const counts = {};
  const pages = {};
  const unavailable = [];

  for (const [name, pathName] of Object.entries(paths)) {
    try {
      const page = await apiRequest(apiBase, pathName, {}, token);
      pages[name] = page;
      counts[name] = Array.isArray(page.items) ? page.items.length : 0;
    } catch (error) {
      counts[name] = 0;
      unavailable.push({ name, error: String(error).slice(0, 240) });
    }
  }

  let journal = null;
  try {
    journal = await apiRequest(apiBase, "/api/v1/acquisition/journal?section_limit=10", {}, token);
    counts.journalEntries = Array.isArray(journal.entries) ? journal.entries.length : 0;
  } catch (error) {
    counts.journalEntries = 0;
    unavailable.push({ name: "journal", error: String(error).slice(0, 240) });
  }

  const proposals = pages.proposals?.items || [];
  const permissions = pages.permissions?.items || [];
  return {
    enabled: unavailable.length === 0,
    counts,
    pages,
    journal,
    unavailable,
    hasSeedData: Object.values(counts).some((count) => count > 0),
    hasActivatedTargets:
      proposals.some((proposal) => ["activated", "rolled_back"].includes(String(proposal.status || ""))) ||
      permissions.some((permission) => String(permission.status || "") === "active"),
  };
}

async function revealSidebarControls(page, title) {
  const row = page.locator("div").filter({ hasText: title }).first();
  await row.hover({ force: true }).catch(() => {});
  const rename = page.getByLabel("Rename conversation").first();
  const archive = page.getByLabel("Archive conversation").first();
  return {
    renameVisible: await rename.isVisible().catch(() => false),
    deleteVisible: await archive.isVisible().catch(() => false),
  };
}

async function readRightPanelAcquisitionSurface(page, timeoutMs) {
  const evidence = {
    present: false,
    capabilityInbox: false,
    acquisitionText: false,
    emptyOrDisabled: false,
    text: "",
  };
  const inboxButton = page.getByRole("button", { name: "Inbox" });
  if ((await inboxButton.count().catch(() => 0)) > 0) {
    await inboxButton.first().click();
  }
  await page.waitForTimeout(Math.min(timeoutMs, 1200));
  const panel = page.getByTestId("acquisition-panel");
  const legacyPanel = page.getByTestId("capability-inbox-panel");
  evidence.capabilityInbox = (await legacyPanel.count().catch(() => 0)) > 0;
  evidence.present = (await panel.count().catch(() => 0)) > 0;
  evidence.text = evidence.present
    ? await panel.first().innerText().catch(() => "")
    : evidence.capabilityInbox
      ? await legacyPanel.first().innerText().catch(() => "")
    : await page.locator("body").innerText().catch(() => "");
  const lower = evidence.text.toLowerCase();
  evidence.acquisitionText = lower.includes("acquisition");
  evidence.emptyOrDisabled = isEmptyOrDisabledAcquisitionText(lower);
  evidence.present = evidence.present && evidence.acquisitionText;
  return evidence;
}

async function verifyChatScrollContainer(page, timeoutMs) {
  await page.getByTestId("chat-scroll-viewport").waitFor({ timeout: timeoutMs });
  return page.getByTestId("chat-scroll-viewport").evaluate((node) => {
    const filler = document.createElement("div");
    filler.setAttribute("data-testid", "qa-scroll-filler");
    filler.style.height = "2200px";
    filler.style.pointerEvents = "none";
    filler.textContent = "temporary acquisition scroll filler";
    node.appendChild(filler);
    const before = node.scrollTop;
    node.scrollTop = Math.max(0, node.scrollHeight - node.clientHeight);
    const after = node.scrollTop;
    filler.remove();
    return {
      before,
      after,
      moved: after > before,
      scrollHeight: node.scrollHeight,
      clientHeight: node.clientHeight,
    };
  });
}

async function openAcquisitionSettingsSurface(page, timeoutMs) {
  const opened = [];
  const button = page.getByRole("button", { name: "Acquisition", exact: true });
  if ((await button.count().catch(() => 0)) > 0) {
    await button.first().click();
    opened.push("Acquisition");
  }
  const section = page.getByTestId("settings-acquisition-section");
  const present = await section
    .first()
    .waitFor({ state: "visible", timeout: timeoutMs })
    .then(() => true)
    .catch(() => false);
  const text = present
    ? await section.first().innerText().catch(() => "")
    : await page.locator("body").innerText().catch(() => "");
  if (present) {
    return {
      present: text.toLowerCase().includes("capability acquisition"),
      opened,
      activeLabel: "Acquisition",
      emptyOrDisabled: isEmptyOrDisabledAcquisitionText(text.toLowerCase()),
      text: text.slice(0, 1000),
    };
  }
  const fallbackText = await page.locator("body").innerText().catch(() => "");
  return {
    present: false,
    opened,
    activeLabel: "",
    emptyOrDisabled: isEmptyOrDisabledAcquisitionText(fallbackText.toLowerCase()),
    text: fallbackText.slice(0, 1000),
  };
}

async function readRenderedAcquisitionEvidence(page) {
  const text = await page.locator("body").innerText().catch(() => "");
  const lower = text.toLowerCase();
  return {
    text: text.slice(0, 4000),
    emptyOrDisabled: isEmptyOrDisabledAcquisitionText(lower),
  };
}

function isEmptyOrDisabledAcquisitionText(lowerText) {
  return (
    lowerText.includes("no capability candidates") ||
    lowerText.includes("no open candidates") ||
    lowerText.includes("no capability gaps") ||
    lowerText.includes("no acquisition gaps") ||
    lowerText.includes("no capability gaps recorded") ||
    lowerText.includes("no acquisition proposals") ||
    lowerText.includes("no acquisition proposals recorded") ||
    lowerText.includes("no acquisition proposals need action") ||
    lowerText.includes("no active runtime acquisition controls") ||
    lowerText.includes("no workers configured") ||
    lowerText.includes("disabled") ||
    lowerText.includes("unavailable")
  );
}

async function readAcquisitionControls(page) {
  const buttonTexts = await page.locator("button").evaluateAll((buttons) =>
    buttons.map((button) => button.textContent?.trim() || "")
  );
  const joined = buttonTexts.join("\n").toLowerCase();
  return {
    approveExploration: joined.includes("approve exploration"),
    approveActivation: joined.includes("approve activation"),
    approve: /\bapprove\b/.test(joined),
    revoke: /\brevoke\b/.test(joined),
    rollback: /\brollback\b/.test(joined),
    buttons: buttonTexts.filter(Boolean).slice(0, 40),
  };
}

module.exports = { createCapabilityAcquisitionSuite };
