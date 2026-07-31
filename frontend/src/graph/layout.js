/**
 * 2D layout only.
 *
 * Every graph in this app is a flat drawing; the 3D scene decides which plane a
 * drawing lives on and never adds depth *within* one. So all layout maths here
 * produces `(x, y)` pairs in local plane coordinates.
 */

import { hierarchy, tree as d3tree } from "d3-hierarchy";
import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
} from "d3-force";

export const NODE_RADIUS = 11;
export const PORT_RADIUS = 13;
export const ROOT_RADIUS = 20;

const NODE_SPACING_X = 64;
const LEVEL_SEPARATION = 185;

const SHELF_GAP = 420;
const SHELF_CELL = 34;
const SHELF_COLUMNS = 12;
const SHELF_BLOCK_GAP = 60;

/**
 * Tidy top-down tree, then flipped so `main` sits at local y = 0 and the tree
 * grows upward. The plane is anchored at the process node on the ground, so
 * "roots at the bottom, leaves at the top" is literal.
 */
export function layoutProcessTree(root) {
  const rooted = hierarchy(root, (node) => node.children);
  const layout = d3tree().nodeSize([NODE_SPACING_X, LEVEL_SEPARATION]);
  layout(rooted);

  const positions = new Map();
  let minX = Infinity;
  let maxX = -Infinity;
  let maxY = 0;

  rooted.each((point) => {
    const x = point.x;
    const y = point.y;
    positions.set(point.data.uid, { x, y });
    minX = Math.min(minX, x);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
  });

  // d3 keeps the root near x = 0 with nodeSize, but only exactly so for
  // symmetric trees. Shift explicitly so the anchor is the root.
  const rootPoint = positions.get(root.uid);
  const shiftX = rootPoint ? rootPoint.x : 0;
  for (const point of positions.values()) point.x -= shiftX;

  return {
    positions,
    bounds: { minX: minX - shiftX, maxX: maxX - shiftX, minY: 0, maxY },
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
 * Bipartite process/resource overview. Force-directed for the organic pyvis
 * feel, then frozen: this plane is the app's fixed frame of reference, so it
 * must not drift while the user is navigating.
 */
export function layoutOverview(overview, { radius = 1500 } = {}) {
  const nodes = [
    ...overview.processes.map((node) => ({ ...node })),
    ...overview.resources.map((node) => ({ ...node })),
  ];
  const byId = new Map(nodes.map((node) => [node.id, node]));

  const links = [];
  for (const edge of overview.edges) {
    const source = byId.get(`process:${edge.processName}`);
    const target = byId.get(`resource:${edge.resourceKey}`);
    if (!source || !target) continue;
    links.push({ ...edge, source, target });
  }

  // Deterministic ring seeding: identical input must produce an identical
  // layout across reloads, so no Math.random anywhere in this file.
  nodes.forEach((node, position) => {
    const angle = (position / nodes.length) * Math.PI * 2;
    const ring = node.type === "process" ? radius * 0.34 : radius * 0.86;
    node.x = Math.cos(angle) * ring;
    node.y = Math.sin(angle) * ring;
  });

  const simulation = forceSimulation(nodes)
    .force(
      "link",
      forceLink(links)
        .id((node) => node.id)
        .distance((link) => (link.target.shared ? 320 : 220))
        .strength(0.45),
    )
    .force("charge", forceManyBody().strength(-2400))
    .force(
      "collide",
      forceCollide().radius((node) => (node.type === "process" ? 130 : 74)),
    )
    .force("x", forceX(0).strength(0.035))
    .force("y", forceY(0).strength(0.035))
    .stop();

  for (let tick = 0; tick < 420; tick += 1) simulation.tick();

  const positions = new Map();
  for (const node of nodes) positions.set(node.id, { x: node.x, y: node.y });
  return { positions, links };
}
