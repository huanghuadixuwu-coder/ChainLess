function apiBaseFor(url, override) {
  if (override) return override;
  const parsed = new URL(url);
  parsed.pathname = "";
  parsed.search = "";
  parsed.hash = "";
  return parsed.toString().replace(/\/$/, "");
}

async function apiRequest(apiBase, pathName, options = {}, token = "") {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(`${apiBase}${pathName}`, {
    ...options,
    headers,
  });
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

module.exports = {
  apiBaseFor,
  apiRequest,
};
