import * as THREE from "three";

/**
 * Flat building blocks. Everything is a 2D shape in the local XY plane so that
 * a plane viewed edge-on collapses to a line, which is the app's decluttering
 * mechanism rather than a rendering accident.
 */

const DISC_GEOMETRY = new THREE.CircleGeometry(1, 40);
const RING_GEOMETRY = new THREE.RingGeometry(0.99, 1.16, 40);

const ARROW_SHAPE = new THREE.Shape();
ARROW_SHAPE.moveTo(0, 0);
ARROW_SHAPE.lineTo(-0.46, -1);
ARROW_SHAPE.lineTo(0.46, -1);
ARROW_SHAPE.lineTo(0, 0);
const ARROW_GEOMETRY = new THREE.ShapeGeometry(ARROW_SHAPE);

function flatMaterial(color, opacity = 1) {
  return new THREE.MeshBasicMaterial({
    color: new THREE.Color(color),
    transparent: true,
    opacity,
    side: THREE.DoubleSide,
    depthWrite: false,
    toneMapped: false,
  });
}

export function createDisc(radius, color, { opacity = 1, renderOrder = 2 } = {}) {
  const mesh = new THREE.Mesh(DISC_GEOMETRY, flatMaterial(color, opacity));
  mesh.scale.setScalar(radius);
  mesh.renderOrder = renderOrder;
  mesh.userData.baseOpacity = opacity;
  return mesh;
}

export function createRing(radius, color, { opacity = 1, renderOrder = 3 } = {}) {
  const mesh = new THREE.Mesh(RING_GEOMETRY, flatMaterial(color, opacity));
  mesh.scale.setScalar(radius);
  mesh.renderOrder = renderOrder;
  mesh.userData.baseOpacity = opacity;
  return mesh;
}

/**
 * Curved edge between two local-plane points, shaped like the vertical cubic
 * bezier the existing pyvis output uses. `bow` bends sibling edges apart so
 * parallel calls between the same pair stay distinguishable.
 */
export function edgePoints(from, to, { bow = 0, segments = 26 } = {}) {
  const start = new THREE.Vector3(from.x, from.y, 0);
  const end = new THREE.Vector3(to.x, to.y, 0);
  const middle = start.clone().add(end).multiplyScalar(0.5);

  // Pull the control point along the perpendicular for the bow, and bias it
  // vertically so the curve leaves the source going "along the tree".
  const delta = end.clone().sub(start);
  const perpendicular = new THREE.Vector3(-delta.y, delta.x, 0).normalize();
  middle.addScaledVector(perpendicular, bow);
  middle.y = middle.y + delta.y * 0.08;

  const curve = new THREE.QuadraticBezierCurve3(start, middle, end);
  return curve.getPoints(segments);
}

export function createEdgeLine(points, color, { opacity = 0.6, renderOrder = 1 } = {}) {
  const geometry = new THREE.BufferGeometry().setFromPoints(points);
  const material = new THREE.LineBasicMaterial({
    color: new THREE.Color(color),
    transparent: true,
    opacity,
    depthWrite: false,
    toneMapped: false,
  });
  const line = new THREE.Line(geometry, material);
  line.renderOrder = renderOrder;
  line.userData.baseOpacity = opacity;
  return line;
}

/** Arrowhead placed at the last point, aimed along the final tangent. */
export function createArrowHead(points, color, { size = 13, opacity = 0.85 } = {}) {
  const tip = points[points.length - 1];
  const previous = points[points.length - 2] || tip;
  const mesh = new THREE.Mesh(ARROW_GEOMETRY, flatMaterial(color, opacity));
  mesh.scale.setScalar(size);
  mesh.position.copy(tip);
  mesh.rotation.z = Math.atan2(tip.y - previous.y, tip.x - previous.x) - Math.PI / 2;
  mesh.renderOrder = 3;
  mesh.userData.baseOpacity = opacity;
  return mesh;
}

/** Trim a curve's endpoints so it starts and stops at the node boundary. */
export function trimToRadius(points, startRadius, endRadius) {
  const trimmed = [...points];
  while (trimmed.length > 2 && trimmed[0].distanceTo(trimmed[trimmed.length - 1]) > 0) {
    if (trimmed[0].distanceTo(points[0]) < startRadius) trimmed.shift();
    else break;
  }
  while (trimmed.length > 2) {
    const last = trimmed[trimmed.length - 1];
    if (last.distanceTo(points[points.length - 1]) < endRadius) trimmed.pop();
    else break;
  }
  return trimmed;
}

export function disposeObject(root) {
  root.traverse((child) => {
    if (child.geometry && child.geometry !== DISC_GEOMETRY && child.geometry !== RING_GEOMETRY && child.geometry !== ARROW_GEOMETRY) {
      child.geometry.dispose();
    }
    const material = child.material;
    if (!material) return;
    // Label textures come from a shared cache and are disposed with it.
    if (Array.isArray(material)) material.forEach((entry) => entry.dispose());
    else material.dispose();
  });
}
