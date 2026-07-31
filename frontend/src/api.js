const jsonHeaders = { Accept: "application/json" };

async function getJson(url) {
  const response = await fetch(url, { headers: jsonHeaders, cache: "no-store" });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(body?.error || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  if (body === null) throw new Error("Response was not valid JSON.");
  return body;
}

export function fetchRuns() {
  return getJson("/api/runs");
}

export function fetchGraph(processName, runId) {
  const query = new URLSearchParams({ process: processName, run: runId });
  return getJson(`/api/graph?${query}`);
}

export function fetchSource(processName, runId, functionId) {
  const query = new URLSearchParams({
    process: processName,
    run: runId,
    function: functionId,
  });
  return getJson(`/api/source?${query}`);
}
