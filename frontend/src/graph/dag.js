/**
 * The call graph as a DAG: one node per function, however many callers it has.
 *
 * The tree in `model.js` duplicates a function once per path from `main`, which
 * is what makes a tidy tree layout possible - and what makes the plane
 * unreadably wide as soon as one utility is called from forty places, because
 * its whole subtree is redrawn under each caller. Here every function is drawn
 * once and the forty callers become forty edges into it.
 *
 * Depth is the *longest* path from the root, so an edge can only ever point
 * from a lower tier to a higher one and the drawing keeps reading bottom-up.
 * Back edges (a call that closes a cycle) are kept, drawn once, and excluded
 * from that calculation, which is what terminates it.
 *
 * The output is deliberately shaped like the tree's: nodes carry `uid`, `fn`
 * and `viaCalls`, so the scene builder, the inspector and the interaction
 * attachment all work on either without knowing which they were given.
 */

import { isLibraryFunction } from "./model.js";

const uidFor = (functionId) => `d:${functionId}`;

export function buildProcessDag(index) {
  const root = index.entryId ? index.functions.get(index.entryId) : null;
  if (!root) return null;

  const nodes = new Map(); // function id -> node
  const outgoing = new Map(); // function id -> Map(target id -> calls[])

  const node = (fn) => {
    if (!nodes.has(fn.id)) {
      nodes.set(fn.id, {
        uid: uidFor(fn.id),
        fn,
        viaCalls: [],
        viaCall: null,
        depth: 0,
        children: [],
        recursive: false,
      });
    }
    return nodes.get(fn.id);
  };

  // --- reachable set, with parallel calls merged onto one edge -------------
  node(root);
  const queue = [root.id];
  while (queue.length > 0) {
    const id = queue.shift();
    const byTarget = new Map();
    for (const call of index.outgoing.get(id) || []) {
      if (!index.functions.has(call.target)) continue;
      if (!byTarget.has(call.target)) byTarget.set(call.target, []);
      byTarget.get(call.target).push(call);
    }
    outgoing.set(id, byTarget);
    for (const targetId of byTarget.keys()) {
      if (isLibraryFunction(index, index.functions.get(targetId))) {
        node(index.functions.get(targetId));
        continue;
      }
      if (nodes.has(targetId)) continue;
      node(index.functions.get(targetId));
      queue.push(targetId);
    }
  }

  // --- topological order, marking the edges that close a cycle ------------
  const backEdges = new Set();
  const finished = [];
  const state = new Map(); // function id -> "open" | "done"
  const stack = [{ id: root.id, iterator: (outgoing.get(root.id) || new Map()).keys() }];
  state.set(root.id, "open");
  while (stack.length > 0) {
    const frame = stack[stack.length - 1];
    const step = frame.iterator.next();
    if (step.done) {
      state.set(frame.id, "done");
      finished.push(frame.id);
      stack.pop();
      continue;
    }
    const targetId = step.value;
    if (state.get(targetId) === "open") {
      backEdges.add(`${frame.id}->${targetId}`);
      continue;
    }
    if (state.get(targetId) === "done") continue;
    state.set(targetId, "open");
    stack.push({ id: targetId, iterator: (outgoing.get(targetId) || new Map()).keys() });
  }

  for (const id of [...finished].reverse()) {
    const depth = nodes.get(id).depth;
    for (const targetId of (outgoing.get(id) || new Map()).keys()) {
      if (backEdges.has(`${id}->${targetId}`)) continue;
      const child = nodes.get(targetId);
      if (child) child.depth = Math.max(child.depth, depth + 1);
    }
  }

  // --- edges ---------------------------------------------------------------
  const edges = [];
  for (const [id, byTarget] of outgoing) {
    const source = nodes.get(id);
    if (!source) continue;
    for (const [targetId, calls] of byTarget) {
      const target = nodes.get(targetId);
      if (!target) continue;
      const recursive = backEdges.has(`${id}->${targetId}`);
      if (recursive) target.recursive = true;
      source.children.push(target);
      target.viaCalls.push(...calls);
      target.viaCall = target.viaCall || calls[0];
      edges.push({
        id: `edge:${source.uid}->${target.uid}`,
        sourceUid: source.uid,
        targetUid: target.uid,
        viaCalls: calls,
        recursive,
      });
    }
  }

  return { root: nodes.get(root.id), nodes: [...nodes.values()], edges };
}
