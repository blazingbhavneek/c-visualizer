import * as THREE from "three";
import { createDisc, createRing } from "./primitives.js";
import { createResourceMark } from "./icons.js";
import { createLabel } from "./labels.js";
import { COLORS, SURFACE, processColor, resourceColor } from "./palette.js";
import { EDGE_CATEGORIES, addEdge, createRegistry, localPosition, registerNode } from "./graphLayer.js";

const PROCESS_RADIUS = 46;
const RESOURCE_RADIUS = 22;

/**
 * The ground plane: processes and daemon resources as one flat graph.
 *
 * This is the app's fixed frame of reference — process planes are anchored to
 * the process node positions produced here. Nodes are addressable and movable,
 * so the layout can be rearranged by the user or by the two-plane arrangement.
 */
export function buildOverviewLayer(overview, layout, { expandedProcesses = new Set() } = {}) {
  const group = new THREE.Group();
  group.name = "overview";
  // Local XY -> world XZ, so the drawing lies flat on the ground.
  group.rotation.x = -Math.PI / 2;

  const registry = createRegistry();
  const pickables = [];
  const labels = [];
  const processIndex = new Map();
  overview.processes.forEach((node, index) => processIndex.set(node.name, index));

  const positionOf = (id) => layout.positions.get(id) || { x: 0, y: 0 };

  // --- resource nodes ------------------------------------------------------
  for (const resource of overview.resources) {
    const point = positionOf(resource.id);
    const color = resourceColor(resource.kind);
    const parts = [];

    const disc = createResourceMark(resource.kind, RESOURCE_RADIUS, color, {
      opacity: resource.resolved ? 1 : 0.3,
    });
    disc.position.set(point.x, point.y, 0.5);
    disc.userData.pick = { type: "resource", resource };
    disc.userData.nodeId = resource.id;
    group.add(disc);
    pickables.push(disc);
    parts.push(disc);

    if (!resource.resolved) {
      const ring = createRing(RESOURCE_RADIUS * 1.25, "#c2185b", { opacity: 0.95 });
      ring.position.copy(disc.position);
      group.add(ring);
      parts.push(ring);
    }
    if (resource.shared) {
      const ring = createRing(RESOURCE_RADIUS * 1.55, COLORS.hairline, { opacity: 0.9 });
      ring.position.copy(disc.position);
      group.add(ring);
      parts.push(ring);
    }

    const label = createLabel([resource.name], {
      worldHeight: 26,
      fontSize: 15,
      color: resource.resolved ? COLORS.ink : "#a3134b",
      halo: SURFACE,
    });
    label.position.set(point.x, point.y - RESOURCE_RADIUS - 22, 0.6);
    group.add(label);
    labels.push(label);
    parts.push(label);

    registerNode(registry, resource.id, {
      kind: "resource",
      mesh: disc,
      parts,
      local: localPosition(point.x, point.y),
      radius: RESOURCE_RADIUS,
      data: resource,
    });
  }

  // --- process nodes -------------------------------------------------------
  for (const process of overview.processes) {
    const point = positionOf(process.id);
    const index = processIndex.get(process.name) ?? 0;
    const expanded = expandedProcesses.has(process.name);
    const color = processColor(index);
    const parts = [];

    const disc = createDisc(PROCESS_RADIUS, color, { opacity: expanded ? 0.3 : 1 });
    disc.position.set(point.x, point.y, 0.8);
    disc.userData.pick = { type: "process", process };
    disc.userData.nodeId = process.id;
    group.add(disc);
    pickables.push(disc);
    parts.push(disc);

    const ring = createRing(PROCESS_RADIUS * 1.18, color, { opacity: expanded ? 1 : 0.45 });
    ring.position.copy(disc.position);
    group.add(ring);
    parts.push(ring);

    const label = createLabel([process.name], {
      worldHeight: 30,
      fontSize: 17,
      color: COLORS.ink,
      bold: true,
      halo: SURFACE,
    });
    label.position.set(point.x, point.y - PROCESS_RADIUS - 40, 0.9);
    group.add(label);
    labels.push(label);
    parts.push(label);

    registerNode(registry, process.id, {
      kind: "process",
      mesh: disc,
      parts,
      local: localPosition(point.x, point.y),
      radius: PROCESS_RADIUS,
      data: process,
      processName: process.name,
    });
  }

  // --- edges ---------------------------------------------------------------
  // Added after the nodes because edge geometry is trimmed to node radii, which
  // the registry only knows once the nodes exist.
  const bowCounters = new Map();
  for (const link of layout.links) {
    const processId = `process:${link.processName}`;
    const resourceId = link.targetId || `resource:${link.resourceKey}`;
    const forward = link.direction !== "in";

    const pairKey = `${processId}|${resourceId}`;
    const seen = bowCounters.get(pairKey) || 0;
    bowCounters.set(pairKey, seen + 1);
    const bow = seen === 0 ? 18 : (seen % 2 === 1 ? 1 : -1) * (18 + Math.ceil(seen / 2) * 26);

    addEdge(registry, group, {
      id: link.id,
      sourceId: forward ? processId : resourceId,
      targetId: forward ? resourceId : processId,
      category: EDGE_CATEGORIES.GROUND,
      color: processColor(processIndex.get(link.processName) ?? 0),
      opacity: 0.55,
      arrowSize: 15,
      arrowOpacity: 0.75,
      bow,
      bidirectional: link.direction === "both",
      labelLines: [
        `${[...link.operations].join(", ")}`,
        `${link.count} call${link.count === 1 ? "" : "s"}`,
      ],
      labelOptions: { worldHeight: 20, fontSize: 13, color: COLORS.inkMuted, halo: SURFACE },
    });
  }

  group.userData.labels = labels;
  return { group, pickables, registry, labels, processIndex };
}
