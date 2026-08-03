import * as THREE from "three";
import { createDisc } from "./primitives.js";

/**
 * Shapes for daemon entities on the ground plane.
 *
 * A file and a queue are different kinds of thing, and a plain dot said so only
 * through its colour and its label. The silhouette says it before either is
 * read. See `frontend/ICONS.md` for how to add one.
 *
 * Every icon is ONE mesh with ONE material built from flat shapes in the local
 * XY plane, because that is what the rest of the scene assumes: picking
 * raycasts non-recursively, dimming multiplies a single `material.opacity`, and
 * a plane seen edge-on has to collapse to a line. A Group would break all
 * three. Shapes are authored at radius 1 and scaled by the caller, exactly like
 * `createDisc`.
 */

/** Database drum: an ellipse cap, straight sides, an ellipse base. */
function databaseShape() {
  const halfWidth = 0.98;
  const capHeight = 0.34;
  const capCentre = 1.02 - capHeight;
  const baseCentre = -1.02 + capHeight;

  const shape = new THREE.Shape();
  shape.moveTo(-halfWidth, capCentre);
  shape.absellipse(0, capCentre, halfWidth, capHeight, Math.PI, 0, true);
  shape.lineTo(halfWidth, baseCentre);
  shape.absellipse(0, baseCentre, halfWidth, capHeight, 0, -Math.PI, true);
  shape.closePath();
  return [shape];
}

/** Queue: three waiting slots, drawn as separated bars. */
function queueShape() {
  const halfWidth = 1.0;
  const barHalfHeight = 0.24;
  return [-0.66, 0, 0.66].map((centre) => {
    const shape = new THREE.Shape();
    shape.moveTo(-halfWidth, centre - barHalfHeight);
    shape.lineTo(halfWidth, centre - barHalfHeight);
    shape.lineTo(halfWidth, centre + barHalfHeight);
    shape.lineTo(-halfWidth, centre + barHalfHeight);
    shape.closePath();
    return shape;
  });
}

/** Library: two slabs stacked with an offset, read as a stack of books. */
function libraryShape() {
  const slab = (centreY, halfWidth, offsetX) => {
    const shape = new THREE.Shape();
    shape.moveTo(offsetX - halfWidth, centreY - 0.3);
    shape.lineTo(offsetX + halfWidth, centreY - 0.3);
    shape.lineTo(offsetX + halfWidth, centreY + 0.3);
    shape.lineTo(offsetX - halfWidth, centreY + 0.3);
    shape.closePath();
    return shape;
  };
  return [slab(-0.42, 1.0, 0), slab(0.42, 0.82, -0.14)];
}

/** kind -> geometry. Add an entry here to give a kind its own icon. */
const ICON_SHAPES = {
  file: databaseShape,
  queue: queueShape,
  library: libraryShape,
};

export function hasResourceIcon(kind) {
  return Boolean(ICON_SHAPES[kind]);
}

/** The mark for one daemon resource: its icon, or a disc for kinds without one. */
export function createResourceMark(kind, radius, color, { opacity = 1, renderOrder = 2 } = {}) {
  if (!ICON_SHAPES[kind]) return createDisc(radius, color, { opacity, renderOrder });

  // A geometry per mark, not a shared one: rebuilding the ground layer runs
  // `disposeObject`, which frees every geometry it did not create itself.
  const mesh = new THREE.Mesh(
    new THREE.ShapeGeometry(ICON_SHAPES[kind]()),
    new THREE.MeshBasicMaterial({
      color: new THREE.Color(color),
      transparent: true,
      opacity,
      side: THREE.DoubleSide,
      depthWrite: false,
      toneMapped: false,
    }),
  );
  mesh.scale.setScalar(radius);
  mesh.renderOrder = renderOrder;
  mesh.userData.baseOpacity = opacity;
  return mesh;
}
