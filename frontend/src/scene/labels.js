import * as THREE from "three";
import { DEVICE_SCALE, fontString, labelCanvasSize } from "../graph/textMetrics.js";

/**
 * Text labels are canvas textures on flat plane meshes, never sprites.
 *
 * That is deliberate: a sprite billboards toward the camera, which would defeat
 * the whole design. A label has to be stuck to its plane and vanish with it
 * when the plane is viewed edge-on.
 *
 * Sizing goes through graph/textMetrics.js, the same module the layout measures
 * with, so spacing decisions and rendered geometry cannot drift apart.
 */

const cache = new Map();

function renderLabelTexture(lines, { fontSize, color, bold, halo }) {
  const canvas = document.createElement("canvas");
  const metrics = labelCanvasSize(lines, { fontSize, bold });
  canvas.width = metrics.width;
  canvas.height = metrics.height;

  const context = canvas.getContext("2d");
  context.font = fontString(fontSize, bold);
  context.textBaseline = "middle";
  context.textAlign = "center";

  lines.forEach((line, index) => {
    const y = metrics.paddingY + metrics.lineHeight * (index + 0.5);
    // A halo in the surface colour punches the text out of whatever passes
    // behind it. Edges cannot be routed around every label, so this is what
    // keeps a label readable when one crosses it.
    if (halo) {
      context.strokeStyle = halo;
      context.lineWidth = fontSize * DEVICE_SCALE * 0.42;
      context.lineJoin = "round";
      context.miterLimit = 2;
      context.strokeText(line, canvas.width / 2, y);
    }
    context.fillStyle = color;
    context.fillText(line, canvas.width / 2, y);
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
    color: options.color ?? "#1c2430",
    bold: options.bold ?? false,
    halo: options.halo ?? null,
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
