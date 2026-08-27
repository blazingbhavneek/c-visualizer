const jsonHeaders = { Accept: "application/json" };
const postJsonHeaders = { ...jsonHeaders, "Content-Type": "application/json" };

async function getJson(url, signal) {
  const response = await fetch(url, { headers: jsonHeaders, cache: "no-store", signal });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const error = new Error(body?.error || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  if (body === null) throw new Error("Response was not valid JSON.");
  return body;
}

export function fetchRuns(signal) {
  return getJson("/api/runs", signal);
}

/**
 * Compact ground-plane data for one run selection. This is the ONLY request
 * that touches every process; process planes load lazily afterwards.
 */
export function fetchOverview(selection, signal) {
  return postJson("/api/overview", { selection }, signal);
}

/** One process's structural bundle: functions (metadata only), calls, resources, interaction links. */
export function fetchProcess(processName, runId, signal) {
  const query = new URLSearchParams({ process: processName, run: runId });
  return getJson(`/api/process?${query}`, signal);
}

/** Everything the Inspector needs for one selected function. */
export function fetchFunctionDetail(processName, runId, functionId, signal) {
  const query = new URLSearchParams({ process: processName, run: runId, function: functionId });
  return getJson(`/api/function?${query}`, signal);
}

/** A synthetic library plane for one shared library component. */
export function fetchLibrary(component, selectionKey, signal) {
  const query = new URLSearchParams({ component, selection: selectionKey });
  return getJson(`/api/library?${query}`, signal);
}

export function fetchSource(processName, runId, functionId, signal) {
  const query = new URLSearchParams({
    process: processName,
    run: runId,
    function: functionId,
  });
  return getJson(`/api/source?${query}`, signal);
}

async function postJson(url, payload, signal) {
  const response = await fetch(url, {
    method: "POST",
    headers: postJsonHeaders,
    body: JSON.stringify(payload),
    signal,
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
