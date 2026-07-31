import { refreshEdge } from "./graphLayer.js";

/**
 * Elastic drag, the way a graph view is expected to behave.
 *
 * Dragging one node used to move only that node, which felt dead and tore its
 * edges to arbitrary lengths. Here the dragged node is pinned to the cursor and
 * everything else settles around it: edges act as springs holding the length
 * they were laid out at, and nodes push apart when their footprints collide.
 *
 * There is deliberately no restoring force toward the original layout. A weak
 * spring home would slowly undo a deliberate rearrangement, so instead nodes
 * stay where the user leaves them and "Reset layout" puts them back.
 */

const SPRING = 0.14;
const REPULSION = 0.22;
const DAMPING = 0.76;
const MAX_STEP = 60;
/** Below this total kinetic energy the graph is considered settled. */
const SETTLED = 0.02;

export function createRelaxation(registry) {
  const nodes = [];
  const index = new Map();
  for (const [id, node] of registry.nodes) {
    const entry = {
      id,
      node,
      x: node.local.x,
      y: node.local.y,
      vx: 0,
      vy: 0,
      clearance: node.clearance ?? node.radius * 2,
    };
    nodes.push(entry);
    index.set(id, entry);
  }

  const links = [];
  for (const edge of registry.edges) {
    const a = index.get(edge.sourceId);
    const b = index.get(edge.targetId);
    if (!a || !b || a === b) continue;
    // Rest length is whatever the layout chose, so relaxing preserves the shape
    // the tidy layout worked out rather than imposing a uniform distance.
    links.push({ a, b, rest: Math.hypot(a.x - b.x, a.y - b.y) || 1 });
  }

  return { registry, nodes, index, links, energy: Infinity };
}

/** True while the graph is still moving and needs another frame. */
export function isSettling(simulation) {
  return simulation && simulation.energy > SETTLED;
}

/**
 * Advance one frame. `pinnedId` is held at its current registry position — the
 * drag owns it — and everything else responds.
 */
export function relaxStep(simulation, pinnedId = null) {
  const { nodes, links, registry } = simulation;

  const pinned = pinnedId ? simulation.index.get(pinnedId) : null;
  if (pinned) {
    pinned.x = pinned.node.local.x;
    pinned.y = pinned.node.local.y;
    pinned.vx = 0;
    pinned.vy = 0;
  }

  for (const entry of nodes) {
    entry.fx = 0;
    entry.fy = 0;
  }

  for (const link of links) {
    const dx = link.b.x - link.a.x;
    const dy = link.b.y - link.a.y;
    const distance = Math.hypot(dx, dy) || 1e-6;
    const force = (SPRING * (distance - link.rest)) / distance;
    link.a.fx += dx * force;
    link.a.fy += dy * force;
    link.b.fx -= dx * force;
    link.b.fy -= dy * force;
  }

  // Pairwise separation. Quadratic, but at a few hundred nodes that is well
  // under a millisecond and it is what stops the spring pass from piling nodes
  // on top of each other.
  for (let i = 0; i < nodes.length; i += 1) {
    const a = nodes[i];
    for (let j = i + 1; j < nodes.length; j += 1) {
      const b = nodes[j];
      const minimum = (a.clearance + b.clearance) / 2;
      let dx = b.x - a.x;
      let dy = b.y - a.y;
      const distanceSquared = dx * dx + dy * dy;
      if (distanceSquared >= minimum * minimum) continue;
      const distance = Math.sqrt(distanceSquared) || 1e-6;
      const push = (REPULSION * (minimum - distance)) / distance;
      dx *= push;
      dy *= push;
      a.fx -= dx;
      a.fy -= dy;
      b.fx += dx;
      b.fy += dy;
    }
  }

  let energy = 0;
  const dirtyEdges = new Set();

  for (const entry of nodes) {
    if (entry === pinned) continue;
    entry.vx = (entry.vx + entry.fx) * DAMPING;
    entry.vy = (entry.vy + entry.fy) * DAMPING;
    entry.vx = Math.max(-MAX_STEP, Math.min(MAX_STEP, entry.vx));
    entry.vy = Math.max(-MAX_STEP, Math.min(MAX_STEP, entry.vy));
    energy += entry.vx * entry.vx + entry.vy * entry.vy;

    if (Math.abs(entry.vx) < 0.01 && Math.abs(entry.vy) < 0.01) continue;
    entry.x += entry.vx;
    entry.y += entry.vy;

    // Move the meshes directly and collect the edges to rebuild, rather than
    // calling moveNode per node: that would refresh shared edges repeatedly.
    const node = entry.node;
    const dx = entry.x - node.local.x;
    const dy = entry.y - node.local.y;
    node.local.set(entry.x, entry.y, node.local.z);
    for (const part of node.parts) {
      part.position.x += dx;
      part.position.y += dy;
    }
    for (const edge of registry.edgesByNode.get(entry.id) || []) dirtyEdges.add(edge);
  }

  if (pinned) {
    for (const edge of registry.edgesByNode.get(pinned.id) || []) dirtyEdges.add(edge);
  }
  for (const edge of dirtyEdges) refreshEdge(registry, edge);

  simulation.energy = energy;
  return dirtyEdges.size > 0;
}

/** Put every node back where the layout originally placed it. */
export function resetToHome(registry) {
  const dirtyEdges = new Set();
  for (const [id, node] of registry.nodes) {
    if (!node.home) continue;
    const dx = node.home.x - node.local.x;
    const dy = node.home.y - node.local.y;
    if (dx === 0 && dy === 0) continue;
    node.local.set(node.home.x, node.home.y, node.local.z);
    for (const part of node.parts) {
      part.position.x += dx;
      part.position.y += dy;
    }
    for (const edge of registry.edgesByNode.get(id) || []) dirtyEdges.add(edge);
  }
  for (const edge of dirtyEdges) refreshEdge(registry, edge);
}
