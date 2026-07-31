/**
 * Scene colours, tuned for the white canvas.
 *
 * Hue identity follows the reference pyvis artifact (red root, amber internal
 * function, green daemon port), but the lightness is snapped so every mark
 * clears the white surface — the reference's own `#00ff1e` and `#ff0000` sit at
 * 1.34:1 and 4.0:1 against white, and the green is unreadable.
 *
 * Validated with the dataviz palette validator against surface #fcfcfb:
 *   roles      #b31414,#cf9010,#0a6e2a,#8b45c0
 *              lightness PASS · chroma PASS · CVD 17.1 PASS · normal 25.4 PASS
 *              amber contrast 2.67 WARN -> relieved by the label every node carries
 *   resources  8 slots, chroma PASS · normal-vision 25.9 PASS
 *              CVD 6.9 WARN (deutan, magenta/green) -> relieved because a
 *              resource label always spells the kind out ("file 0x1007"), so
 *              hue is redundant rather than load-bearing.
 */

export const SURFACE = "#fcfcfb";

export const COLORS = {
  entry: "#b31414",
  internal: "#cf9010",
  staticInternal: "#b87f0c",
  port: "#0a6e2a",
  library: "#7b8798",
  recursive: "#8b45c0",
  unreached: "#9aa5b4",
  edge: "#b0864a",
  edgeMuted: "#c8cdd6",
  crossPlane: "#0e7fa8",
  planeToPlane: "#c2185b",
  ground: "#eef1f5",
  /** Fill for a raised plane, so it reads as paper rather than a colour wash. */
  sheet: "#f2f5f9",

  /** Ink, for anything that is text or a hairline rather than a data mark. */
  ink: "#1c2430",
  inkMuted: "#5c6675",
  inkFaint: "#8c95a3",
  hairline: "#c3cad4",
  selection: "#0f1720",
};

/**
 * Resource kinds. Ordered so the weakest CVD pair is not adjacent; the label
 * under every node names the kind, so this is scanning aid, not the encoding.
 */
export const RESOURCE_COLORS = {
  file: "#2563d8",
  queue: "#d18a00",
  event: "#8b3fd6",
  semaphore: "#16913f",
  process: "#d0157a",
  message: "#0e9aa8",
  daemon_resource: "#a24b12",
};

export const PROCESS_COLORS = [
  "#2563d8",
  "#d18a00",
  "#8b3fd6",
  "#16913f",
  "#d0157a",
  "#0e9aa8",
  "#a24b12",
  "#4a5bbf",
];

export function resourceColor(kind) {
  return RESOURCE_COLORS[kind] || "#4a5bbf";
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
