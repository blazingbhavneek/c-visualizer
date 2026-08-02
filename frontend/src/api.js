const jsonHeaders = { Accept: "application/json" };
const postJsonHeaders = { ...jsonHeaders, "Content-Type": "application/json" };

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

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: postJsonHeaders,
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(body?.error || body?.message || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return body;
}

function dispatchSseBlock(block, onEvent) {
  let type = "message";
  const data = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) type = line.slice(6).trim();
    if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (data.length === 0) return null;
  const raw = data.join("\n");
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch {
    payload = { message: "Invalid JSON in event stream.", raw };
    type = "error";
  }
  onEvent?.(type, payload);
  return type;
}

/** Consume the frozen POST SSE contract. Resolves after the response closes. */
export async function askStream(payload, { signal, onEvent } = {}) {
  const response = await fetch("/api/ask/stream", {
    method: "POST",
    headers: { ...postJsonHeaders, Accept: "text/event-stream" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const error = new Error(body?.error || body?.message || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  if (!response.body) throw new Error("Streaming response body is unavailable.");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const terminalEvents = new Set(["answer", "error", "cancelled"]);
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    buffer = buffer.replaceAll("\r\n", "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const type = dispatchSseBlock(buffer.slice(0, boundary), onEvent);
      buffer = buffer.slice(boundary + 2);
      if (terminalEvents.has(type)) {
        await reader.cancel();
        return;
      }
      boundary = buffer.indexOf("\n\n");
    }
    if (done) break;
  }
  if (buffer.trim()) dispatchSseBlock(buffer, onEvent);
}

export function cancelAsk(runId) {
  return postJson("/api/ask/cancel", { run_id: runId });
}

export function wikiStatus() {
  return getJson("/api/wiki/status");
}
