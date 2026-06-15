function prefixSteps(prefix, result) {
  return (result.steps || []).map((step) => ({
    ...step,
    name: `${prefix}:${step.name}`,
  }));
}

function mergeScreenshots(results) {
  return results.flatMap((result) => result.screenshots || []);
}

function createSpecCompleteSuite({
  apiBaseFor,
  apiRequest,
  loginViaUi,
  applyBootstrapAdminCredentials,
  runSmoke,
  runWorkstream10,
  runSettings,
  getSuite,
}) {
  return async function runSpecComplete(page, args, reportDir) {
    const apiBase = apiBaseFor(args.url, args.apiUrl);
    const steps = [];
    const results = [];

    applyBootstrapAdminCredentials(args);
    const suiteArgs = {
      ...args,
      credentialsExplicit: true,
    };

    const token = await loginViaUi(page, suiteArgs);
    if (!token) throw new Error("Spec-complete login did not store a token");
    steps.push({ name: "auth-login", ok: true });

    const refreshed = await apiRequest(
      apiBase,
      "/api/v1/auth/refresh",
      { method: "POST" },
      token
    );
    const me = await apiRequest(apiBase, "/api/v1/auth/me", {}, refreshed.access_token);
    steps.push({
      name: "auth-refresh-me",
      ok: Boolean(refreshed.access_token && me.role === "admin"),
    });

    const smoke = await runSmoke(page, suiteArgs, reportDir);
    results.push(smoke);
    steps.push(...prefixSteps("smoke", smoke));

    const workstream10 = await runWorkstream10(page, suiteArgs, reportDir);
    results.push(workstream10);
    steps.push(...prefixSteps("workstream10", workstream10));

    const settings = await runSettings(page, suiteArgs, reportDir);
    results.push(settings);
    steps.push(...prefixSteps("settings", settings));

    const artifacts = await getSuite("artifacts")(page, suiteArgs, reportDir);
    results.push(artifacts);
    steps.push(...prefixSteps("artifacts", artifacts));

    const richInput = await getSuite("rich-input")(page, suiteArgs, reportDir);
    results.push(richInput);
    steps.push(...prefixSteps("rich-input", richInput));

    const cleanupChecks = steps.filter((step) => step.name.includes("cleanup"));
    steps.push({
      name: "cleanup-verification",
      ok: cleanupChecks.length >= 4 && cleanupChecks.every((step) => step.ok),
      cleanupSteps: cleanupChecks.map((step) => step.name),
    });

    return {
      steps,
      screenshots: mergeScreenshots(results),
    };
  };
}

module.exports = {
  createSpecCompleteSuite,
};
