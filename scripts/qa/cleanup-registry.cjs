const { apiRequest } = require("./api-client.cjs");

async function cleanupConversations(apiBase, token, ids) {
  const results = [];
  for (const id of [...new Set(ids.filter(Boolean))]) {
    try {
      await apiRequest(apiBase, `/api/v1/conversations/${id}?purge=true`, { method: "DELETE" }, token);
      results.push({ id, ok: true });
    } catch (error) {
      if (String(error).includes("CONVERSATION_NOT_FOUND")) {
        results.push({ id, ok: true, alreadyRemoved: true });
        continue;
      }
      results.push({ id, ok: false, error: String(error) });
    }
  }
  return results;
}

module.exports = {
  cleanupConversations,
};
