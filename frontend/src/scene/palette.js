export const COLORS = {
  entry: "#ff2d2d",
  internal: "#f69e05",
  staticInternal: "#e08a2e",
  port: "#12dd6a",
  library: "#68758a",
  recursive: "#b06bd8",
  unreached: "#4a5568",
  edge: "#b8802a",
  edgeMuted: "#566274",
  crossPlane: "#38d9ff",
  planeToPlane: "#ff5fa2",
  ground: "#1b2432",
};

export const RESOURCE_COLORS = {
  file: "#4aa3ff",
  queue: "#c678dd",
  event: "#ffd166",
  semaphore: "#ff8fa3",
  process: "#7bd88f",
  message: "#56d4c4",
  daemon_resource: "#9aa7ff",
};

export const PROCESS_COLORS = [
  "#ff9f43",
  "#4aa3ff",
  "#7bd88f",
  "#c678dd",
  "#ffd166",
  "#56d4c4",
  "#ff8fa3",
  "#9aa7ff",
];

export function resourceColor(kind) {
  return RESOURCE_COLORS[kind] || "#9aa7ff";
}

export function processColor(index) {
  return PROCESS_COLORS[index % PROCESS_COLORS.length];
}

/** Node fill for a function, by role in the tree. */
export function functionColor(fn, { isEntry = false, isPort = false, recursive = false } = {}) {
  if (isEntry) return COLORS.entry;
  if (recursive) return COLORS.recursive;
  if (isPort) return COLORS.port;
  if (fn.is_external) return COLORS.library;
  if (fn.is_static) return COLORS.staticInternal;
  return COLORS.internal;
}
