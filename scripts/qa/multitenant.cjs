#!/usr/bin/env node

const { spawnSync } = require("child_process");

function parseArgs(argv) {
  const args = {
    baseUrl: "http://backend-test-server:8000",
    tenants: "3",
    parallelPerTenant: "5",
    rebuild: true,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--base-url") args.baseUrl = argv[++i] || args.baseUrl;
    else if (arg === "--tenants") args.tenants = argv[++i] || args.tenants;
    else if (arg === "--parallel-per-tenant") {
      args.parallelPerTenant = argv[++i] || args.parallelPerTenant;
    } else if (arg === "--no-build") {
      args.rebuild = false;
    }
  }
  return args;
}

function composeArgs(extra) {
  return [
    "-f",
    "docker-compose.yml",
    "-f",
    "docker-compose.test.yml",
    ...extra,
  ];
}

function run(command, args) {
  const result = spawnSync(command, args, {
    cwd: process.cwd(),
    env: process.env,
    stdio: "inherit",
    shell: process.platform === "win32",
  });
  if (result.status !== 0) {
    process.exit(result.status || 1);
  }
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.rebuild) {
    run("docker-compose", composeArgs(["build", "backend-test", "backend-test-server"]));
  }
  run("docker-compose", composeArgs(["up", "-d", "backend-test-server"]));
  run(
    "docker-compose",
    composeArgs([
      "run",
      "--rm",
      "backend-test",
      "sh",
      "-c",
      [
        "cd /repo/backend",
        "PYTHONPATH=/repo/backend",
        "python scripts/multitenant_probe.py",
        `--base-url ${args.baseUrl}`,
        `--tenants ${args.tenants}`,
        `--parallel-per-tenant ${args.parallelPerTenant}`,
        "--json",
      ].join(" "),
    ])
  );
}

main();
