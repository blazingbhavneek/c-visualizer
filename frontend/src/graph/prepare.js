import {
  attachInteractions,
  buildProcessTree,
  collectUnreached,
  coverageSummary,
  flattenTree,
  portFunctionNames,
} from "./model.js";
import { buildProcessDag } from "./dag.js";
import { layoutProcessDag, layoutProcessTree, layoutUnreachedShelf } from "./layout.js";

/**
 * `entry_function_id` can be null. The documented fallback is graph roots, so
 * synthesise a root over every internal function nothing else calls.
 */
function withVirtualRoot(index) {
  const roots = [];
  for (const fn of index.functions.values()) {
    if (fn.is_external) continue;
    const incoming = index.incoming.get(fn.id) || [];
    const outgoing = index.outgoing.get(fn.id) || [];
    if (incoming.length === 0 && outgoing.length > 0) roots.push(fn);
  }
  if (roots.length === 0) return null;

  const virtualIndex = {
    ...index,
    entryId: "__virtual_root__",
    functions: new Map(index.functions),
    outgoing: new Map(index.outgoing),
  };
  virtualIndex.functions.set("__virtual_root__", {
    id: "__virtual_root__",
    kind: "function",
    name: `${index.process.name} (graph roots)`,
    file: null,
    file_name: null,
    start_line: -1,
    end_line: -1,
    is_external: false,
    is_static: false,
    summary_status: "pending",
    summary: null,
    call_count: roots.length,
    resource_interaction_count: 0,
    synthetic: true,
  });
  virtualIndex.outgoing.set(
    "__virtual_root__",
    roots.map((fn) => ({
      id: `call:virtual:${fn.id}`,
      source: "__virtual_root__",
      target: fn.id,
      line: null,
      kind: "direct",
      via: null,
    })),
  );
  return virtualIndex;
}

/** Tree nodes know their single parent; the scene draws from an edge list. */
function treeEdges(nodes) {
  return nodes
    .filter((node) => node.parent)
    .map((node) => ({
      id: `edge:${node.parent.uid}->${node.uid}`,
      sourceUid: node.parent.uid,
      targetUid: node.uid,
      viaCalls: node.viaCalls,
      recursive: node.recursive,
    }));
}

/**
 * Everything one process plane needs, computed once when the process is
 * expanded. Pure data — no three.js types cross this boundary.
 *
 * `mode` picks the shape of the drawing: the tree duplicates a function per
 * path, the DAG draws it once with an edge per caller.
 */
export function prepareProcess(
  index,
  { mode = "tree", showIsolated = false, sharedNames = null } = {},
) {
  let working = index;
  let syntheticRoot = false;
  if (!index.entryId || !index.functions.has(index.entryId)) {
    working = withVirtualRoot(index);
    if (!working) return null;
    syntheticRoot = true;
  }
  const entryFunctionId = syntheticRoot ? "__virtual_root__" : index.entryId;

  let tree = null;
  let treeNodes = [];
  let edges = [];
  if (mode === "dag") {
    const dag = buildProcessDag(working);
    if (!dag) return null;
    tree = dag.root;
    treeNodes = dag.nodes;
    edges = dag.edges;
  } else {
    tree = buildProcessTree(working);
    if (!tree) return null;
    treeNodes = flattenTree(tree);
    edges = treeEdges(treeNodes);
  }

  const portNames = portFunctionNames(index);
  const treeLayout =
    mode === "dag"
      ? layoutProcessDag(treeNodes, edges, { entryFunctionId, portNames })
      : layoutProcessTree(tree, { entryFunctionId, portNames });
  const unreachedGroups = collectUnreached(index, treeNodes, { showIsolated, sharedNames });
  const shelf = layoutUnreachedShelf(unreachedGroups, treeLayout.bounds);
  const coverage = coverageSummary(index, treeNodes, unreachedGroups);
  const attachments = attachInteractions(index, treeNodes);

  return {
    processName: index.process.name,
    index,
    mode,
    tree,
    treeNodes,
    edges,
    treeLayout,
    unreachedGroups,
    shelf,
    coverage,
    attachments,
    portNames,
    entryFunctionId,
    syntheticRoot,
  };
}
