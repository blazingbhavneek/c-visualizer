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
 * How far each ring may stray from where it sat when the drag began, indexed by
 * hops from the dragged node.
 *
 * This is a hard clamp rather than a stiff spring. Stiffness was tried and is
 * numerically unstable: with explicit integration, an anchor of k=3 overshoots
 * every frame and the node oscillates, which is what made distant nodes flicker
 * when an edge was stretched far. A clamp is unconditionally stable and says
 * exactly what it means - the second ring shifts a little, the rest barely.
 */
const MAX_DRIFT_BY_HOP = [0, Infinity, 45];
const MAX_DRIFT_DISTANT = 6;
/** Gentle pull back toward the anchor, well inside the stability limit. */
const ANCHOR_STIFFNESS = 0.18;
/** Ceiling on any single edge's pull, so a stretched edge cannot explode. */
const MAX_LINK_FORCE = 24;

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

  return {
    registry,
    nodes,
    index,
    links,
    adjacency,
    energy: Infinity,
    maxPenetration: 0,
    pinnedId: null,
  };
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
    entry.maxDrift = MAX_DRIFT_DISTANT;
    entry.anchorX = entry.x;
    entry.anchorY = entry.y;
  }
  if (!pinnedId) return;

  const seen = new Set([pinnedId]);
  let frontier = [pinnedId];
  for (let hop = 0; hop < MAX_DRIFT_BY_HOP.length && frontier.length > 0; hop += 1) {
    const next = [];
    for (const id of frontier) {
      const entry = simulation.index.get(id);
      if (entry) entry.maxDrift = MAX_DRIFT_BY_HOP[hop];
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
    // Everything holds roughly where it was dropped; the remaining frames only
    // resolve overlap. Rings that were already tightly clamped keep their
    // clamp, or the settle would hand them a second budget to drift with.
    entry.maxDrift = Math.min(entry.maxDrift ?? MAX_DRIFT_DISTANT, 40);
  }
  simulation.pinnedId = null;
}

/**
 * True while the graph still needs another frame.
 *
 * Energy alone is not enough: the settle threshold could be reached while two
 * marks were still overlapping, leaving the no-overlap guarantee broken. The
 * simulation is not finished until nothing is penetrating.
 */
export function isSettling(simulation) {
  if (!simulation) return false;
  return simulation.energy > SETTLED || simulation.maxPenetration > 1;
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
    entry.penetration = 0;
  }

  for (const link of links) {
    const dx = link.b.x - link.a.x;
    const dy = link.b.y - link.a.y;
    const distance = Math.hypot(dx, dy) || 1e-6;
    // Capped: a hugely stretched edge would otherwise apply a force large
    // enough to fling its endpoints past each other and oscillate.
    const pull = Math.max(
      -MAX_LINK_FORCE,
      Math.min(MAX_LINK_FORCE, SPRING * (distance - link.rest)),
    );
    const force = pull / distance;
    link.a.fx += dx * force;
    link.a.fy += dy * force;
    link.b.fx -= dx * force;
    link.b.fy -= dy * force;
  }

  for (const entry of nodes) {
    if (entry.maxDrift === Infinity || entry.anchorX === undefined) continue;
    entry.fx += (entry.anchorX - entry.x) * ANCHOR_STIFFNESS;
    entry.fy += (entry.anchorY - entry.y) * ANCHOR_STIFFNESS;
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
      const overlap = minimum - distance;
      a.penetration = Math.max(a.penetration, overlap);
      b.penetration = Math.max(b.penetration, overlap);
      const push = (REPULSION * overlap) / distance;
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

    if (Math.abs(entry.vx) < 0.01 && Math.abs(entry.vy) < 0.01) continue;
    const previousX = entry.x;
    const previousY = entry.y;
    entry.x += entry.vx;
    entry.y += entry.vy;

    // Hard clamp to the ring's allowance. Bleeding off the velocity at the
    // boundary is what stops a node pressed against its limit from buzzing.
    // A node may borrow exactly enough extra drift to clear a collision. Without
    // this a tightly clamped ring cannot escape an overlap the drag created, and
    // the no-overlap guarantee quietly breaks for distant pairs.
    const allowance = entry.maxDrift ?? MAX_DRIFT_DISTANT;
    const limit = Math.max(allowance, entry.penetration * 1.6);
    if (limit !== Infinity && entry.anchorX !== undefined) {
      const ox = entry.x - entry.anchorX;
      const oy = entry.y - entry.anchorY;
      const drift = Math.hypot(ox, oy);
      if (drift > limit) {
        const scale = limit / drift;
        entry.x = entry.anchorX + ox * scale;
        entry.y = entry.anchorY + oy * scale;
        entry.vx *= 0.2;
        entry.vy *= 0.2;
      }
    }

    // Energy is measured from the distance actually travelled, not from
    // velocity. A node held against its drift clamp keeps a non-zero velocity
    // forever - anchor pulling in, edge spring pulling out - so a
    // velocity-based measure never fell below the settle threshold and the
    // simulation ran every frame for the rest of the session.
    const movedX = entry.x - previousX;
    const movedY = entry.y - previousY;
    energy += movedX * movedX + movedY * movedY;

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
  let maxPenetration = 0;
  for (const entry of nodes) maxPenetration = Math.max(maxPenetration, entry.penetration || 0);
  simulation.maxPenetration = maxPenetration;
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
