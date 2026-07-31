import * as THREE from "three";
import { createArrowHead, createDisc, createEdgeLine, createRing, edgePoints, trimToRadius } from "./primitives.js";
import { createLabel } from "./labels.js";
import { COLORS, functionColor } from "./palette.js";
import { NODE_RADIUS, PORT_RADIUS, ROOT_RADIUS } from "../graph/layout.js";

const LIBRARY_RADIUS = 8;
const UNREACHED_RADIUS = 7;

function radiusFor(node, isEntry, isPort) {
  if (isEntry) return ROOT_RADIUS;
  if (isPort) return PORT_RADIUS;
  if (node.fn.is_external) return LIBRARY_RADIUS;
  return NODE_RADIUS;
}

function labelLines(fn) {
  if (fn.is_external || !fn.file_name) return [fn.name];
  const range = fn.start_line > 0 ? `[${fn.start_line}:${fn.end_line}]` : "";
  return [`[${fn.file_name}]`, `${fn.name}${range}`];
}

/**
 * One process plane: the full call tree rooted at `main`, plus the unreached
 * shelf that accounts for every remaining internal function.
 *
 * Built entirely in local XY with `main` at the origin, so the caller can place
 * the group at the process's ground anchor and orient it with a quaternion.
 */
export function buildProcessPlaneLayer({
  treeNodes,
  treeLayout,
  shelf,
  portNames,
  entryFunctionId,
  processTint,
  coverage,
  processName,
}) {
  const group = new THREE.Group();
  group.name = `plane:${processName}`;

  const pickables = [];
  const labels = [];
  const nodeAnchors = new Map();

  const bounds = {
    minX: Math.min(treeLayout.bounds.minX, shelf.bounds.minX),
    maxX: Math.max(treeLayout.bounds.maxX, shelf.bounds.maxX),
    minY: Math.min(treeLayout.bounds.minY, shelf.bounds.minY),
    maxY: Math.max(treeLayout.bounds.maxY, shelf.bounds.maxY),
  };

  // Backdrop: gives the plane presence head-on and vanishes edge-on, which is
  // exactly the behaviour the layered design depends on.
  const padding = 140;
  const backdrop = new THREE.Mesh(
    new THREE.PlaneGeometry(bounds.maxX - bounds.minX + padding * 2, bounds.maxY - bounds.minY + padding * 2),
    new THREE.MeshBasicMaterial({
      color: new THREE.Color(processTint),
      transparent: true,
      opacity: 0.045,
      side: THREE.DoubleSide,
      depthWrite: false,
      toneMapped: false,
    }),
  );
  backdrop.position.set(
    (bounds.minX + bounds.maxX) / 2,
    (bounds.minY + bounds.maxY) / 2,
    -1.5,
  );
  backdrop.renderOrder = 0;
  backdrop.userData.baseOpacity = 0.045;
  group.add(backdrop);

  // --- tree edges ----------------------------------------------------------
  const bowCounters = new Map();
  for (const node of treeNodes) {
    if (!node.parent) continue;
    const from = treeLayout.positions.get(node.parent.uid);
    const to = treeLayout.positions.get(node.uid);
    if (!from || !to) continue;

    const pairKey = `${node.parent.uid}->${node.fn.id}`;
    const seen = bowCounters.get(pairKey) || 0;
    bowCounters.set(pairKey, seen + 1);
    const bow = seen === 0 ? 0 : (seen % 2 === 1 ? 1 : -1) * Math.ceil(seen / 2) * 26;

    const isPort = portNames.has(node.fn.name);
    const targetRadius = radiusFor(node, false, isPort);
    const sourceRadius = radiusFor(node.parent, node.parent.fn.id === entryFunctionId, false);

    const raw = edgePoints(from, to, { bow });
    const points = trimToRadius(raw, sourceRadius + 3, targetRadius + 5);
    const color = node.recursive ? COLORS.recursive : COLORS.edge;
    const line = createEdgeLine(points, color, { opacity: node.recursive ? 0.55 : 0.5 });
    group.add(line);
    group.add(createArrowHead(points, color, { size: 11, opacity: 0.75 }));

    // One edge can stand for several call sites; show every line number so the
    // merge stays visible rather than looking like a single call.
    const lineNumbers = (node.viaCalls || [])
      .map((call) => call.line)
      .filter((value) => value != null);
    if (lineNumbers.length > 0) {
      const shown =
        lineNumbers.length > 3
          ? `${lineNumbers.slice(0, 3).join(", ")} +${lineNumbers.length - 3}`
          : lineNumbers.join(", ");
      const midpoint = points[Math.floor(points.length / 2)];
      const edgeLabel = createLabel([shown], {
        worldHeight: 17,
        fontSize: 12,
        color: "#9aa7b8",
      });
      edgeLabel.position.set(midpoint.x, midpoint.y, 0.2);
      edgeLabel.userData.detailLabel = true;
      group.add(edgeLabel);
      labels.push(edgeLabel);
    }
  }

  // --- tree nodes ----------------------------------------------------------
  for (const node of treeNodes) {
    const point = treeLayout.positions.get(node.uid);
    if (!point) continue;

    const isEntry = node.fn.id === entryFunctionId && !node.parent;
    const isPort = portNames.has(node.fn.name);
    const radius = radiusFor(node, isEntry, isPort);
    const color = functionColor(node.fn, { isEntry, isPort, recursive: node.recursive });

    const disc = createDisc(radius, color, { opacity: node.fn.is_external && !isPort ? 0.6 : 1 });
    disc.position.set(point.x, point.y, 0.5);
    disc.userData.pick = { type: "function", node, processName };
    group.add(disc);
    pickables.push(disc);

    if (node.fn.is_static) {
      const ring = createRing(radius * 1.3, "#ffffff", { opacity: 0.28 });
      ring.position.copy(disc.position);
      group.add(ring);
    }
    if (node.recursive) {
      const ring = createRing(radius * 1.5, COLORS.recursive, { opacity: 0.8 });
      ring.position.copy(disc.position);
      group.add(ring);
    }

    const lines = labelLines(node.fn);
    const label = createLabel(lines, {
      worldHeight: isEntry ? 26 : 21,
      fontSize: isEntry ? 16 : 14,
      color: isEntry ? "#ffd9d9" : isPort ? "#b6ffd4" : "#cdd8e8",
      bold: isEntry,
    });
    label.position.set(point.x, point.y - radius - 8 - lines.length * 10, 0.6);
    // The root and the daemon API ports keep their labels at any distance -
    // they are what the plane is *for*. Everything else is detail, hidden until
    // the camera is close, which keeps a 120-node tree from becoming a wall of
    // text the moment it is framed.
    label.userData.detailLabel = !isEntry && !isPort;
    group.add(label);
    labels.push(label);

    nodeAnchors.set(node.uid, new THREE.Vector3(point.x, point.y, 0));
  }

  // --- unreached shelf -----------------------------------------------------
  for (const block of shelf.blocks) {
    const header = createLabel(
      [block.file, `${block.count} off-tree · ${block.isolated} with no calls at all`],
      { worldHeight: 20, fontSize: 13, color: "#7f8ca0" },
    );
    header.position.set(block.x + block.width / 2, block.y + 16, 0.4);
    header.userData.detailLabel = true;
    group.add(header);
    labels.push(header);
  }

  for (const placement of shelf.placements) {
    // Brighter dots have recorded calls but no path from main; dimmer ones have
    // no recorded call in either direction.
    const disc = createDisc(UNREACHED_RADIUS, COLORS.unreached, {
      opacity: placement.isolated ? 0.55 : 0.95,
    });
    disc.position.set(placement.x, placement.y, 0.5);
    disc.userData.pick = {
      type: "function",
      node: {
        uid: `unreached:${placement.fn.id}`,
        fn: placement.fn,
        children: [],
        unreached: true,
        isolated: placement.isolated,
      },
      processName,
    };
    group.add(disc);
    pickables.push(disc);
  }

  if (shelf.placements.length > 0) {
    const caption = createLabel(
      [
        "NOT REACHABLE FROM main",
        `${coverage.unreached} of ${coverage.internal} internal functions · ${coverage.isolated} have no recorded call at all`,
      ],
      { worldHeight: 24, fontSize: 14, color: "#6f7c90" },
    );
    caption.position.set(
      shelf.bounds.minX + (shelf.bounds.maxX - shelf.bounds.minX) / 2,
      shelf.bounds.maxY + 60,
      0.4,
    );
    group.add(caption);
    labels.push(caption);
  }

  return { group, pickables, nodeAnchors, labels, bounds };
}
