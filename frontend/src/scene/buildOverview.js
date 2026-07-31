import * as THREE from "three";
import { createArrowHead, createDisc, createEdgeLine, createRing, edgePoints, trimToRadius } from "./primitives.js";
import { createLabel } from "./labels.js";
import { COLORS, processColor, resourceColor } from "./palette.js";

const PROCESS_RADIUS = 46;
const RESOURCE_RADIUS = 22;

/**
 * The ground plane: processes and daemon resources as one flat bipartite graph.
 *
 * This is the app's fixed frame of reference. Process planes are anchored to
 * the process node positions produced here, so this layout is computed once and
 * then frozen.
 */
export function buildOverviewLayer(overview, layout, { expandedProcesses = new Set() } = {}) {
  const group = new THREE.Group();
  group.name = "overview";
  // Local XY -> world XZ, so the drawing lies flat on the ground.
  group.rotation.x = -Math.PI / 2;

  const pickables = [];
  const anchors = new Map();
  const labels = [];
  const processIndex = new Map();
  overview.processes.forEach((node, index) => processIndex.set(node.name, index));

  const positionOf = (id) => layout.positions.get(id) || { x: 0, y: 0 };

  // --- edges first, so nodes draw over them -------------------------------
  for (const link of layout.links) {
    const from = positionOf(link.source.id);
    const to = positionOf(link.target.id);
    const muted = expandedProcesses.has(link.processName);
    const color = muted ? COLORS.edgeMuted : processColor(processIndex.get(link.processName) ?? 0);
    const opacity = muted ? 0.16 : 0.55;

    const forward = link.direction !== "in";
    const raw = edgePoints(forward ? from : to, forward ? to : from, { bow: 18 });
    const points = trimToRadius(
      raw,
      forward ? PROCESS_RADIUS : RESOURCE_RADIUS,
      forward ? RESOURCE_RADIUS : PROCESS_RADIUS,
    );
    const line = createEdgeLine(points, color, { opacity });
    line.userData.overviewEdge = link;
    group.add(line);
    group.add(createArrowHead(points, color, { size: 15, opacity: opacity + 0.2 }));

    if (link.direction === "both") {
      const reverse = [...points].reverse();
      group.add(createArrowHead(reverse, color, { size: 15, opacity: opacity + 0.2 }));
    }
  }

  // --- resource nodes ------------------------------------------------------
  for (const resource of overview.resources) {
    const point = positionOf(resource.id);
    const color = resourceColor(resource.kind);
    const disc = createDisc(RESOURCE_RADIUS, color, { opacity: resource.resolved ? 1 : 0.3 });
    disc.position.set(point.x, point.y, 0.5);
    disc.userData.pick = { type: "resource", resource };
    group.add(disc);
    pickables.push(disc);

    if (!resource.resolved) {
      const ring = createRing(RESOURCE_RADIUS * 1.25, "#c2185b", { opacity: 0.95 });
      ring.position.copy(disc.position);
      group.add(ring);
    }
    if (resource.shared) {
      const ring = createRing(RESOURCE_RADIUS * 1.55, COLORS.hairline, { opacity: 0.9 });
      ring.position.copy(disc.position);
      group.add(ring);
    }

    const label = createLabel([`${resource.kind} ${resource.name}`], {
      worldHeight: 26,
      fontSize: 15,
      color: resource.resolved ? COLORS.ink : "#a3134b",
      bold: false,
    });
    label.position.set(point.x, point.y - RESOURCE_RADIUS - 22, 0.6);
    group.add(label);
    labels.push(label);

    anchors.set(resource.id, new THREE.Vector3(point.x, point.y, 0));
  }

  // --- process nodes -------------------------------------------------------
  for (const process of overview.processes) {
    const point = positionOf(process.id);
    const index = processIndex.get(process.name) ?? 0;
    const expanded = expandedProcesses.has(process.name);
    const color = processColor(index);

    const disc = createDisc(PROCESS_RADIUS, color, { opacity: expanded ? 0.3 : 1 });
    disc.position.set(point.x, point.y, 0.8);
    disc.userData.pick = { type: "process", process };
    group.add(disc);
    pickables.push(disc);

    const ring = createRing(PROCESS_RADIUS * 1.18, color, { opacity: expanded ? 1 : 0.45 });
    ring.position.copy(disc.position);
    group.add(ring);

    const label = createLabel(
      [process.name, `${process.functionCount} fn · ${process.interactionCount} interactions`],
      { worldHeight: 30, fontSize: 17, color: COLORS.ink, bold: true },
    );
    label.position.set(point.x, point.y - PROCESS_RADIUS - 40, 0.9);
    group.add(label);
    labels.push(label);

    anchors.set(process.id, new THREE.Vector3(point.x, point.y, 0));
  }

  group.userData.labels = labels;
  return { group, pickables, anchors, processIndex };
}

/** World position of an overview node, accounting for the group transform. */
export function overviewWorldPosition(group, anchors, id) {
  const local = anchors.get(id);
  if (!local) return null;
  return local.clone().applyMatrix4(group.matrixWorld);
}
