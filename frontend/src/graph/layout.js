/**
 * 2D layout only.
 *
 * Every graph in this app is a flat drawing; the 3D scene decides which plane a
 * drawing lives on and never adds depth *within* one. So all layout maths here
 * produces `(x, y)` pairs in local plane coordinates.
 */

import { hierarchy, tree as d3tree } from "d3-hierarchy";
import { forceCollide, forceSimulation } from "d3-force";
import { LABEL_SPECS, labelWorldSize } from "./textMetrics.js";

export const NODE_RADIUS = 11;
export const PORT_RADIUS = 13;
export const ROOT_RADIUS = 20;

const LEVEL_SEPARATION = 215;
/** Clear space left between two neighbouring footprints. */
const SIBLING_GAP = 26;
const LIBRARY_RADIUS = 8;

const SHELF_GAP = 420;
const SHELF_CELL = 34;
const SHELF_COLUMNS = 12;
const SHELF_BLOCK_GAP = 60;

/**
 * Horizontal space one node needs: whichever is wider, its dot or its label.
 *
 * Spacing on the dot radius alone is what made every tier collide - a dot is 22
 * units across and `compute_3element_feedwater_setpoint` is over 300.
 */
function footprintWidth(node, { entryFunctionId, portNames }) {
  const isEntry = node.fn.id === entryFunctionId && !node.parent;
  const isPort = portNames?.has(node.fn.name);
  const radius = isEntry
    ? ROOT_RADIUS
    : isPort
      ? PORT_RADIUS
      : node.fn.is_external
        ? LIBRARY_RADIUS
        : NODE_RADIUS;
  const spec = isEntry ? LABEL_SPECS.treeRoot : LABEL_SPECS.treeNode;
  const label = labelWorldSize([node.fn.name], spec);
  return Math.max(radius * 2, label.width);
}

/**
 * Tidy top-down tree, then flipped so `main` sits at local y = 0 and the tree
 * grows upward. The plane is anchored at the process node on the ground, so
 * "roots at the bottom, leaves at the top" is literal.
 *
 * Separation is measured, not fixed: `nodeSize` is one unit wide and the
 * separation function returns the actual clearance the two neighbours need,
 * which is what guarantees no node or label overlaps another.
 */
export function layoutProcessTree(root, { entryFunctionId = null, portNames = null } = {}) {
  const rooted = hierarchy(root, (node) => node.children);

  const widths = new Map();
  rooted.each((point) => {
    widths.set(point.data.uid, footprintWidth(point.data, { entryFunctionId, portNames }));
  });
  const widthOf = (point) => widths.get(point.data.uid) ?? NODE_RADIUS * 2;

  const layout = d3tree()
    .nodeSize([1, LEVEL_SEPARATION])
    .separation((a, b) => {
      const clearance = (widthOf(a) + widthOf(b)) / 2 + SIBLING_GAP;
      // Cousins get extra room so subtrees read as separate blocks.
      return a.parent === b.parent ? clearance : clearance * 1.35;
    });
  layout(rooted);

  const positions = new Map();
  let minX = Infinity;
  let maxX = -Infinity;
  let maxY = 0;

  rooted.each((point) => {
    positions.set(point.data.uid, { x: point.x, y: point.y });
    minX = Math.min(minX, point.x - widthOf(point) / 2);
    maxX = Math.max(maxX, point.x + widthOf(point) / 2);
    maxY = Math.max(maxY, point.y);
  });

  // d3 keeps the root near x = 0 with nodeSize, but only exactly so for
  // symmetric trees. Shift explicitly so the anchor is the root.
  const rootPoint = positions.get(root.uid);
  const shiftX = rootPoint ? rootPoint.x : 0;
  for (const point of positions.values()) point.x -= shiftX;

  return {
    positions,
    widths,
    bounds: { minX: minX - shiftX, maxX: maxX - shiftX, minY: 0, maxY },
  };
}

/**
 * Layered layout for the DAG view.
 *
 * Every function is on the tier given by its longest path from the root, so all
 * edges point one way. Within a tier the order is decided by the average
 * position of a node's neighbours (a barycentre sweep, down then up, repeated):
 * that is what pulls a heavily reused function underneath the callers that
 * share it instead of leaving it wherever it was first met, and it is the
 * difference between readable and a wall of crossing lines.
 *
 * Spacing uses the same measured footprints as the tree, so labels cannot
 * collide here either, and no physics runs afterwards - reloading the same
 * snapshot always gives the same drawing.
 */
export function layoutProcessDag(nodes, edges, { entryFunctionId = null, portNames = null } = {}) {
  const widths = new Map();
  for (const node of nodes) {
    widths.set(node.uid, footprintWidth(node, { entryFunctionId, portNames }));
  }

  const tiers = [];
  for (const node of nodes) {
    if (!tiers[node.depth]) tiers[node.depth] = [];
    tiers[node.depth].push(node);
  }
  for (let depth = 0; depth < tiers.length; depth += 1) {
    if (!tiers[depth]) tiers[depth] = [];
  }

  const parents = new Map();
  const children = new Map();
  for (const edge of edges) {
    // A back edge would drag its target down to its own tier; it is drawn, not
    // used for placement.
    if (edge.recursive) continue;
    if (!children.has(edge.sourceUid)) children.set(edge.sourceUid, []);
    children.get(edge.sourceUid).push(edge.targetUid);
    if (!parents.has(edge.targetUid)) parents.set(edge.targetUid, []);
    parents.get(edge.targetUid).push(edge.sourceUid);
  }

  const x = new Map();
  const pack = (tier) => {
    if (tier.length === 0) return;
    const wanted = tier.map((node) => x.get(node.uid) ?? 0);
    let cursor = 0;
    tier.forEach((node, position) => {
      if (position > 0) {
        cursor +=
          widths.get(tier[position - 1].uid) / 2 +
          SIBLING_GAP +
          widths.get(node.uid) / 2;
      }
      x.set(node.uid, cursor);
    });
    // Packing starts at zero, so slide the whole tier back to where its members
    // wanted to be; otherwise every tier is left-aligned and the edges skew.
    const wantedMean = wanted.reduce((sum, value) => sum + value, 0) / tier.length;
    const packedMean =
      tier.reduce((sum, node) => sum + x.get(node.uid), 0) / tier.length;
    const shift = wantedMean - packedMean;
    for (const node of tier) x.set(node.uid, x.get(node.uid) + shift);
  };

  const barycentre = (uid, neighbours) => {
    const list = neighbours.get(uid) || [];
    const known = list.map((other) => x.get(other)).filter((value) => value != null);
    if (known.length === 0) return null;
    return known.reduce((sum, value) => sum + value, 0) / known.length;
  };

  const orderTier = (tier, neighbours) => {
    const keys = new Map();
    tier.forEach((node, position) => {
      keys.set(node.uid, barycentre(node.uid, neighbours) ?? x.get(node.uid) ?? position);
    });
    tier.sort((a, b) => keys.get(a.uid) - keys.get(b.uid));
    for (const node of tier) x.set(node.uid, keys.get(node.uid));
    pack(tier);
  };

  pack(tiers[0] || []);
  for (let round = 0; round < 3; round += 1) {
    for (let depth = 1; depth < tiers.length; depth += 1) orderTier(tiers[depth], parents);
    for (let depth = tiers.length - 2; depth >= 0; depth -= 1) {
      orderTier(tiers[depth], children);
    }
  }

  // The plane is anchored at the root, exactly as in the tree layout.
  const rootShift = tiers[0]?.[0] ? x.get(tiers[0][0].uid) : 0;
  const positions = new Map();
  let minX = Infinity;
  let maxX = -Infinity;
  for (const node of nodes) {
    const px = (x.get(node.uid) ?? 0) - rootShift;
    positions.set(node.uid, { x: px, y: node.depth * LEVEL_SEPARATION });
    minX = Math.min(minX, px - widths.get(node.uid) / 2);
    maxX = Math.max(maxX, px + widths.get(node.uid) / 2);
  }

  return {
    positions,
    widths,
    bounds: {
      minX: Number.isFinite(minX) ? minX : 0,
      maxX: Number.isFinite(maxX) ? maxX : 0,
      minY: 0,
      maxY: Math.max(0, tiers.length - 1) * LEVEL_SEPARATION,
    },
  };
}

/**
 * Unreached functions: a quiet grid to the right of the tree, blocked by source
 * file. They have no edges, so this is about accounting for every function on
 * the plane without letting them compete with the tree.
 */
export function layoutUnreachedShelf(groups, treeBounds) {
  const originX = treeBounds.maxX + SHELF_GAP;
  const placements = [];
  const blocks = [];
  let cursorY = treeBounds.maxY;

  for (const group of groups) {
    const rows = Math.ceil(group.functions.length / SHELF_COLUMNS);
    const blockHeight = rows * SHELF_CELL;
    const blockTop = cursorY;

    group.functions.forEach((fn, position) => {
      const column = position % SHELF_COLUMNS;
      const row = Math.floor(position / SHELF_COLUMNS);
      placements.push({
        fn,
        isolated: group.isolatedIds?.has(fn.id) ?? true,
        x: originX + column * SHELF_CELL,
        y: blockTop - row * SHELF_CELL,
      });
    });

    blocks.push({
      file: group.file,
      count: group.functions.length,
      isolated: group.isolated,
      linked: group.linked,
      x: originX,
      y: blockTop + SHELF_CELL * 0.9,
      width: SHELF_COLUMNS * SHELF_CELL,
      height: blockHeight,
    });

    cursorY = blockTop - blockHeight - SHELF_BLOCK_GAP;
  }

  return {
    placements,
    blocks,
    bounds: {
      minX: originX - SHELF_CELL,
      maxX: originX + SHELF_COLUMNS * SHELF_CELL,
      minY: cursorY,
      maxY: treeBounds.maxY + SHELF_CELL * 2,
    },
  };
}

/**
 * Affinity layout for the process/daemon overview.
 *
 * A plain force layout put resources wherever the physics settled, so the plane
 * read as a hairball. Two rows would be no better: with 24 of 36 resources
 * shared, a bipartite split just routes every edge across the gap.
 *
 * Instead, position carries meaning. Processes sit evenly on a ring. Each
 * resource is placed at the *angular centroid of the processes that touch it*,
 * so a resource physically sits between its users; its radius falls as more
 * processes share it, which pushes exclusive resources outboard next to their
 * single owner and pulls widely shared ones toward the middle. Edges then run
 * mostly radially and stay short.
 *
 * Only collision relaxation runs afterwards, so the structural placement
 * survives and the result is deterministic across reloads.
 */
export function layoutOverview(overview, { radius = 1500 } = {}) {
  const processes = overview.processes.map((node) => ({ ...node }));
  const resources = overview.resources.map((node) => ({ ...node }));
  const nodes = [...processes, ...resources];
  const byId = new Map(nodes.map((node) => [node.id, node]));

  const links = [];
  for (const edge of overview.edges) {
    const source = byId.get(`process:${edge.processName}`);
    // `targetId` is usually the resource, but an event addressed to another
    // process points straight at that process node.
    const target = byId.get(edge.targetId || `resource:${edge.resourceKey}`);
    if (!source || !target) continue;
    links.push({ ...edge, source, target });
  }

  // --- processes evenly on the inner ring, in a stable order ---------------
  const ordered = [...processes].sort((a, b) => a.name.localeCompare(b.name));
  const processRadius = radius * 0.46;
  const angleOf = new Map();
  ordered.forEach((process, position) => {
    const angle = (position / ordered.length) * Math.PI * 2 - Math.PI / 2;
    angleOf.set(process.name, angle);
    process.x = Math.cos(angle) * processRadius;
    process.y = Math.sin(angle) * processRadius;
    // Pinned during relaxation: processes are the frame of reference, so
    // resources must be pushed clear of their *final* positions. Re-pinning
    // afterwards instead would undo the collision resolution around them.
    process.fx = process.x;
    process.fy = process.y;
  });

  // --- resources at the angular centroid of their users --------------------
  for (const resource of resources) {
    const users = [...resource.processes].filter((name) => angleOf.has(name));
    if (users.length === 0) {
      resource.x = 0;
      resource.y = 0;
      continue;
    }

    // Average the direction vectors rather than the angles, so the wrap at
    // +/-pi does not throw the mean to the opposite side of the ring.
    let sumX = 0;
    let sumY = 0;
    for (const name of users) {
      const angle = angleOf.get(name);
      sumX += Math.cos(angle);
      sumY += Math.sin(angle);
    }
    const spread = Math.hypot(sumX, sumY) / users.length; // 1 = agreed, 0 = opposed
    const meanAngle = Math.atan2(sumY, sumX);

    // Exclusive resources sit outboard of their owner; the more processes share
    // a resource, and the more they disagree on direction, the further in it
    // sits, until a resource used by everyone lands near the centre.
    const shareFactor = 1 / users.length;
    const resourceRadius =
      processRadius * (0.42 + 0.78 * shareFactor) * (0.35 + 0.65 * spread) +
      processRadius * 0.55 * shareFactor;

    resource.x = Math.cos(meanAngle) * resourceRadius;
    resource.y = Math.sin(meanAngle) * resourceRadius;
  }

  // --- collision-only relaxation ------------------------------------------
  // Nudges overlapping marks apart without letting physics redesign the layout.
  // Collision radius covers the label, not just the dot, so no mark overlaps
  // another mark's text. Labels sit below their node, so the vertical extent is
  // roughly the label height on top of the dot.
  for (const node of nodes) {
    const isProcess = node.type === "process" || node.type === "library";
    const spec = isProcess ? LABEL_SPECS.process : LABEL_SPECS.resource;
    const lines = [node.name];
    const label = labelWorldSize(lines, spec);
    const dot = isProcess ? 46 : 22;
    node.clearance = Math.max(dot * 1.7, label.width / 2 + 26, label.height + dot * 1.2);
  }

  const simulation = forceSimulation(nodes)
    .force(
      "collide",
      forceCollide()
        .radius((node) => node.clearance)
        .strength(0.95),
    )
    .alphaDecay(0.045)
    .stop();
  for (let tick = 0; tick < 500; tick += 1) simulation.tick();

  const positions = new Map();
  for (const node of nodes) positions.set(node.id, { x: node.x, y: node.y });
  return { positions, links, processAngles: angleOf, processRadius };
}
