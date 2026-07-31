/**
 * One source of truth for label geometry.
 *
 * Layout has to know how wide a label will be *before* the label mesh exists,
 * otherwise nodes get spaced on their dot radius alone and every tier collides.
 * The renderer (scene/labels.js) and the layout both size text through here, so
 * the two can never drift apart.
 *
 * Falls back to a monospace character-width estimate when there is no DOM, so
 * layout stays runnable headless.
 */

export const DEVICE_SCALE = 2;
export const FONT_STACK = 'ui-monospace, "SF Mono", Menlo, monospace';
/** Advance width of one character as a fraction of font size, for the fallback. */
const MONOSPACE_RATIO = 0.6;

/** Label styling shared by the builders, so layout can measure what will render. */
export const LABEL_SPECS = {
  treeRoot: { worldHeight: 26, fontSize: 16, bold: true },
  treeNode: { worldHeight: 21, fontSize: 14, bold: false },
  process: { worldHeight: 30, fontSize: 17, bold: true },
  resource: { worldHeight: 26, fontSize: 15, bold: false },
};

let sharedContext = null;
function context2d() {
  if (sharedContext !== null) return sharedContext;
  if (typeof document === "undefined") {
    sharedContext = false;
    return sharedContext;
  }
  sharedContext = document.createElement("canvas").getContext("2d");
  return sharedContext;
}

export function fontString(fontSize, bold) {
  return `${bold ? "700 " : ""}${fontSize * DEVICE_SCALE}px ${FONT_STACK}`;
}

function measureTextWidth(text, fontSize, bold) {
  const context = context2d();
  if (!context) return text.length * fontSize * DEVICE_SCALE * MONOSPACE_RATIO;
  context.font = fontString(fontSize, bold);
  return context.measureText(text).width;
}

/** Canvas pixel dimensions for a label, including padding. */
export function labelCanvasSize(lines, { fontSize, bold }) {
  const widths = lines.map((line) => measureTextWidth(line, fontSize, bold));
  const lineHeight = fontSize * DEVICE_SCALE * 1.32;
  const paddingX = fontSize * DEVICE_SCALE * 0.6;
  const paddingY = fontSize * DEVICE_SCALE * 0.4;
  return {
    width: Math.max(8, Math.ceil(Math.max(...widths, 0) + paddingX * 2)),
    height: Math.max(8, Math.ceil(lineHeight * lines.length + paddingY * 2)),
    lineHeight,
    paddingY,
  };
}

/** World-unit footprint of a label, matching what createLabel will build. */
export function labelWorldSize(lines, spec) {
  const canvas = labelCanvasSize(lines, spec);
  const height = spec.worldHeight * lines.length;
  return { width: height * (canvas.width / canvas.height), height };
}
