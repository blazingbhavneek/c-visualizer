import * as THREE from "three";

/**
 * Text labels are canvas textures on flat plane meshes, never sprites.
 *
 * That is deliberate: a sprite billboards toward the camera, which would defeat
 * the whole design. A label has to be stuck to its plane and vanish with it
 * when the plane is viewed edge-on.
 */

const cache = new Map();
const DEVICE_SCALE = 2;

function renderLabelTexture(lines, { fontSize, color, bold, background }) {
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  const font = `${bold ? "700 " : ""}${fontSize * DEVICE_SCALE}px ui-monospace, "SF Mono", Menlo, monospace`;

  context.font = font;
  const widths = lines.map((line) => context.measureText(line).width);
  const lineHeight = fontSize * DEVICE_SCALE * 1.32;
  const paddingX = fontSize * DEVICE_SCALE * 0.6;
  const paddingY = fontSize * DEVICE_SCALE * 0.4;

  canvas.width = Math.max(8, Math.ceil(Math.max(...widths) + paddingX * 2));
  canvas.height = Math.max(8, Math.ceil(lineHeight * lines.length + paddingY * 2));

  const context2 = canvas.getContext("2d");
  if (background) {
    context2.fillStyle = background;
    context2.fillRect(0, 0, canvas.width, canvas.height);
  }
  context2.font = font;
  context2.textBaseline = "middle";
  context2.textAlign = "center";
  context2.fillStyle = color;
  lines.forEach((line, index) => {
    context2.fillText(line, canvas.width / 2, paddingY + lineHeight * (index + 0.5));
  });

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.minFilter = THREE.LinearMipmapLinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.anisotropy = 8;
  texture.needsUpdate = true;
  return { texture, aspect: canvas.width / canvas.height };
}

export function getLabelTexture(lines, options = {}) {
  const settings = {
    fontSize: options.fontSize ?? 15,
    color: options.color ?? "#dfe6f0",
    bold: options.bold ?? false,
    background: options.background ?? null,
  };
  const key = JSON.stringify([lines, settings]);
  if (!cache.has(key)) cache.set(key, renderLabelTexture(lines, settings));
  return cache.get(key);
}

/**
 * A flat, plane-locked text mesh. `worldHeight` is the height of one text line
 * in local plane units, so callers size labels relative to node radii.
 */
export function createLabel(lines, { worldHeight = 26, ...options } = {}) {
  const { texture, aspect } = getLabelTexture(lines, options);
  const height = worldHeight * lines.length;
  const geometry = new THREE.PlaneGeometry(height * aspect, height);
  const material = new THREE.MeshBasicMaterial({
    map: texture,
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    toneMapped: false,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.renderOrder = 4;
  mesh.userData.isLabel = true;
  mesh.userData.baseOpacity = 1;
  return mesh;
}

export function disposeLabelCache() {
  for (const entry of cache.values()) entry.texture.dispose();
  cache.clear();
}
