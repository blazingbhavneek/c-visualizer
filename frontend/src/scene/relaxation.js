import { refreshEdge } from "./graphLayer.js";

/**
 * Elastic drag, the way a graph view is expected to behave.
 *
 * Dragging one node used to move only that node, which felt dead and tore its
 * edges to arbitrary lengths. Here the dragged node is pinned to the cursor and
 * everything else settles around it: edges act as springs holding the length
 * they were laid out at, and nodes push apart when their footprints collide.
 *
 * Influence is gated by hop distance from the dragged node. Without that gate,
 * the collision pass alone shoves the whole graph around - dragging one process
 * visibly moved every node on the plane. Immediate neighbours follow properly;
 * anything further only drifts enough to keep out of the way.
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

/**
 * Stiffness of the spring holding each ring to where it sat when the drag
 * began, indexed by hops from the dragged node.
 *
 * Scaling per-frame velocity is not enough on its own: a slower node still
 * converges to the same equilibrium, it just takes more frames, so the second
 * ring was ending up 137 units away. Anchoring moves the equilibrium itself.
 * Direct neighbours are unanchored and follow properly; beyond that the anchor
 * dominates the edge springs and nodes only shift enough to stay clear.
 */
const ANCHOR_BY_HOP = [0, 0, 1.3];
const ANCHOR_DISTANT = 3;

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

  const adjacency = new Map();
  for (const link of links) {
    if (!adjacency.has(link.a.id)) adjacency.set(link.a.id, []);
    if (!adjacency.has(link.b.id)) adjacency.set(link.b.id, []);
    adjacency.get(link.a.id).push(link.b.id);
    adjacency.get(link.b.id).push(link.a.id);
  }

  return { registry, nodes, index, links, adjacency, energy: Infinity, pinnedId: null };
}

/**
 * Assign each node a mobility from its hop distance to the dragged node.
 * Recomputed only when the drag target changes, not per frame.
 */
export function setPinned(simulation, pinnedId) {
  if (simulation.pinnedId === pinnedId) return;
  simulation.pinnedId = pinnedId;

  // Anchors are taken from current positions, not the original layout, so a
  // second drag starts from wherever the user left things.
  for (const entry of simulation.nodes) {
    entry.anchor = ANCHOR_DISTANT;
    entry.anchorX = entry.x;
    entry.anchorY = entry.y;
  }
  if (!pinnedId) return;

  const seen = new Set([pinnedId]);
  let frontier = [pinnedId];
  for (let hop = 0; hop < ANCHOR_BY_HOP.length && frontier.length > 0; hop += 1) {
    const next = [];
    for (const id of frontier) {
      const entry = simulation.index.get(id);
      if (entry) entry.anchor = ANCHOR_BY_HOP[hop];
      for (const neighbour of simulation.adjacency.get(id) || []) {
        if (seen.has(neighbour)) continue;
        seen.add(neighbour);
        next.push(neighbour);
      }
    }
    frontier = next;
  }
}

/**
 * Hand over on mouse-up: every node keeps the position it now holds.
 *
 * Without this the anchored outer rings simply spring the dragged cluster back
 * to where it started, so the drag had no lasting effect at all. Re-anchoring
 * on release is what makes a rearrangement stick while still letting the last
 * few frames resolve any remaining overlap.
 */
export function releasePin(simulation) {
  if (!simulation) return;
  for (const entry of simulation.nodes) {
    entry.anchorX = entry.x;
    entry.anchorY = entry.y;
    if (!entry.anchor) entry.anchor = 0.5;
  }
  simulation.pinnedId = null;
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

  for (const entry of nodes) {
    if (!entry.anchor) continue;
    entry.fx += (entry.anchorX - entry.x) * entry.anchor;
    entry.fy += (entry.anchorY - entry.y) * entry.anchor;
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
