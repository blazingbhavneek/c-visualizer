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
 * Build the curve for an edge, in local plane coordinates.
 *
 * `vertical` mirrors the reference artifact's `forceDirection: "vertical"`: the
 * curve leaves the parent going straight up and arrives at the child going
 * straight down, so it stays in the corridor between two tiers instead of
 * cutting across the neighbours' labels.
 */
function edgeCurve(from, to, { bow = 0, mode = "bowed" } = {}) {
  const start = new THREE.Vector3(from.x, from.y, 0);
  const end = new THREE.Vector3(to.x, to.y, 0);
  const delta = end.clone().sub(start);

  if (mode === "vertical") {
    const reach = Math.abs(delta.y) * 0.55 || 40;
    const sign = Math.sign(delta.y) || 1;
    return new THREE.CubicBezierCurve3(
      start,
      new THREE.Vector3(start.x + bow * 0.4, start.y + sign * reach, 0),
      new THREE.Vector3(end.x + bow * 0.4, end.y - sign * reach, 0),
      end,
    );
  }

  const middle = start.clone().add(end).multiplyScalar(0.5);
  const perpendicular = new THREE.Vector3(-delta.y, delta.x, 0).normalize();
  middle.addScaledVector(perpendicular, bow);
  middle.y += delta.y * 0.08;
  return new THREE.QuadraticBezierCurve3(start, middle, end);
}

/**
 * Sample an edge as a FIXED number of points, always `segments + 1`.
 *
 * The count must never vary. BufferGeometry.setFromPoints only overwrites
 * min(points, capacity) vertices and never shrinks the buffer, so a refresh
 * that produced fewer points than the last one left stale vertices behind and
 * the line drew a segment back to wherever the node used to be - edges looked
 * jumpy and torn while dragging.
 *
 * Clearing the node discs is therefore done by trimming the curve's *parameter*
 * range rather than dropping points off the ends.
 */
export function edgePoints(
  from,
  to,
  { bow = 0, segments = 26, mode = "bowed", startRadius = 0, endRadius = 0 } = {},
) {
  const curve = edgeCurve(from, to, { bow, mode });
  const head = curve.getPoint(0);
  const tail = curve.getPoint(1);

  const PROBE = 32;
  const scratch = new THREE.Vector3();
  let from_t = 0;
  let to_t = 1;
  for (let i = 0; i <= PROBE; i += 1) {
    const t = i / PROBE;
    if (curve.getPoint(t, scratch).distanceTo(head) >= startRadius) {
      from_t = t;
      break;
    }
  }
  for (let i = 0; i <= PROBE; i += 1) {
    const t = 1 - i / PROBE;
    if (curve.getPoint(t, scratch).distanceTo(tail) >= endRadius) {
      to_t = t;
      break;
    }
  }
  // Endpoints overlapping (nodes dragged on top of each other) would invert the
  // range; keep a short stub at the midpoint so the count still holds.
  if (to_t <= from_t) {
    from_t = 0.48;
    to_t = 0.52;
  }

  const points = [];
  for (let i = 0; i <= segments; i += 1) {
    points.push(curve.getPoint(from_t + (to_t - from_t) * (i / segments)));
  }
  return points;
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
