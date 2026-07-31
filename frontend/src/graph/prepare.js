import {
  attachInteractions,
  buildProcessTree,
  collectUnreached,
  coverageSummary,
  flattenTree,
  portFunctionNames,
} from "./model.js";
import { layoutProcessTree, layoutUnreachedShelf } from "./layout.js";

/**
 * Everything one process plane needs, computed once when the process is
 * expanded. Pure data — no three.js types cross this boundary.
 */
export function prepareProcess(index) {
  let tree = buildProcessTree(index);
  let syntheticRoot = false;

  // `entry_function_id` can be null. The documented fallback is graph roots, so
  // synthesise a root over every internal function nothing else calls.
  if (!tree) {
    const roots = [];
    for (const fn of index.functions.values()) {
      if (fn.is_external) continue;
      const incoming = index.incoming.get(fn.id) || [];
      const outgoing = index.outgoing.get(fn.id) || [];
      if (incoming.length === 0 && outgoing.length > 0) roots.push(fn);
    }
    if (roots.length === 0) return null;

    syntheticRoot = true;
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
    tree = buildProcessTree(virtualIndex);
    if (!tree) return null;
  }

  const treeNodes = flattenTree(tree);
  const portNames = portFunctionNames(index);
  const treeLayout = layoutProcessTree(tree, {
    entryFunctionId: syntheticRoot ? "__virtual_root__" : index.entryId,
    portNames,
  });
  const unreachedGroups = collectUnreached(index, treeNodes);
  const shelf = layoutUnreachedShelf(unreachedGroups, treeLayout.bounds);
  const coverage = coverageSummary(index, treeNodes, unreachedGroups);
  const attachments = attachInteractions(index, treeNodes);

  return {
    processName: index.process.name,
    index,
    tree,
    treeNodes,
    treeLayout,
    unreachedGroups,
    shelf,
    coverage,
    attachments,
    portNames,
    entryFunctionId: syntheticRoot ? "__virtual_root__" : index.entryId,
    syntheticRoot,
  };
}
