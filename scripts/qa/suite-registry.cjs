const suites = new Map();

function registerSuite(name, runner) {
  suites.set(name, runner);
}

function getSuite(name) {
  const suite = suites.get(name);
  if (!suite) {
    throw new Error(`Unknown QA suite: ${name}`);
  }
  return suite;
}

function listSuites() {
  return [...suites.keys()];
}

module.exports = {
  getSuite,
  listSuites,
  registerSuite,
};
