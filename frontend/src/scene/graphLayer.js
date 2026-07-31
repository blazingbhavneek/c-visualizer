import * as THREE from "three";
import { createArrowHead, createEdgeLine, edgePoints } from "./primitives.js";
import { createLabel } from "./labels.js";

/**
 * The addressable graph layer shared by the ground plane and the process planes.
 *
 * Both builders produce the same shape: a node registry keyed by id and an edge
 * list whose geometry can be recomputed from current node positions. That is
 * what makes dragging, per-category toggling, fading and hover highlighting
 * possible at all — a flat THREE.Group has no way to answer "which edges touch
 * this node".
 */

export const EDGE_CATEGORIES = {
  CALL: "call",
  INTERACTION: "interaction",
  GROUND: "ground",
  PLANE_TO_PLANE: "planeToPlane",
};

export function createRegistry() {
  return {
    nodes: new Map(),
    edges: [],
    edgesByNode: new Map(),
  };
}

export function registerNode(registry, id, entry) {
  const node = { id, parts: [], ...entry };
  // `home` is where the layout put it, so a rearrangement can be undone.
  node.home = { x: node.local.x, y: node.local.y };
  // `clearance` is the footprint the relaxation keeps free: the label is wider
  // than the dot for almost every node, so using the radius would let text
  // collide the moment anything moves.
  if (node.clearance == null) {
    let widest = node.radius * 2;
    for (const part of node.parts) {
      if (part.userData?.isLabel && part.geometry?.parameters) {
        widest = Math.max(widest, part.geometry.parameters.width);
      }
    }
    node.clearance = widest;
  }
  registry.nodes.set(id, node);
  if (!registry.edgesByNode.has(id)) registry.edgesByNode.set(id, []);
  return node;
}

function link(registry, nodeId, edge) {
  if (!registry.edgesByNode.has(nodeId)) registry.edgesByNode.set(nodeId, []);
  registry.edgesByNode.get(nodeId).push(edge);
}

/**
 * Build one in-plane edge and register it.
 *
 * `bow` offsets parallel edges between the same pair so they stay separable,
 * mirroring the CW/CCW fan the reference pyvis artifact uses.
 */
export function addEdge(
  registry,
  group,
  {
    id,
    sourceId,
    targetId,
    category,
    color,
    opacity = 0.7,
    arrowSize = 11,
    arrowOpacity = 0.9,
    bow = 0,
    curveMode = "bowed",
    bidirectional = false,
    labelLines = null,
    labelOptions = {},
    z = 0.2,
  },
) {
  const source = registry.nodes.get(sourceId);
  const target = registry.nodes.get(targetId);
  if (!source || !target) return null;

  const edge = {
    id,
    sourceId,
    targetId,
    category,
    bow,
    curveMode,
    bidirectional,
    color,
    baseOpacity: opacity,
    arrowBaseOpacity: arrowOpacity,
    arrowSize,
    z,
    line: null,
    arrows: [],
    label: null,
  };

  const points = edgeGeometryPoints(source, target, edge);
  edge.line = createEdgeLine(points, color, { opacity });
  edge.line.userData.edge = edge;
  group.add(edge.line);

  const head = createArrowHead(points, color, { size: arrowSize, opacity: arrowOpacity });
  edge.arrows.push(head);
  group.add(head);
  if (bidirectional) {
    const tail = createArrowHead([...points].reverse(), color, {
      size: arrowSize,
      opacity: arrowOpacity,
    });
    edge.arrows.push(tail);
    group.add(tail);
  }

  if (labelLines) {
    edge.label = createLabel(labelLines, labelOptions);
    // Edge labels are permanently off; the hover layer turns individual ones on.
    // Left always-visible they are the single messiest thing on either plane.
    edge.label.visible = false;
    edge.label.userData.edgeLabel = true;
    group.add(edge.label);
    positionEdgeLabel(edge, points);
  }

  registry.edges.push(edge);
  link(registry, sourceId, edge);
  link(registry, targetId, edge);
  return edge;
}

function edgeGeometryPoints(source, target, edge) {
  return edgePoints(source.local, target.local, {
    bow: edge.bow,
    mode: edge.curveMode,
    startRadius: source.radius + 3,
    endRadius: target.radius + 5,
  });
}

function positionEdgeLabel(edge, points) {
  if (!edge.label) return;
  const midpoint = points[Math.floor(points.length / 2)];
  edge.label.position.set(midpoint.x, midpoint.y, edge.z + 0.4);
}

/** Recompute one edge's geometry from its endpoints' current positions. */
export function refreshEdge(registry, edge) {
  const source = registry.nodes.get(edge.sourceId);
  const target = registry.nodes.get(edge.targetId);
  if (!source || !target) return;

  const points = edgeGeometryPoints(source, target, edge);
  // Written in place: the count is fixed, so this never leaves stale vertices.
  const position = edge.line.geometry.getAttribute("position");
  for (let i = 0; i < points.length && i < position.count; i += 1) {
    position.setXYZ(i, points[i].x, points[i].y, points[i].z);
  }
  position.needsUpdate = true;
  edge.line.geometry.computeBoundingSphere();

  const tip = points[points.length - 1];
  const beforeTip = points[points.length - 2] || tip;
  edge.arrows[0]?.position.copy(tip);
  if (edge.arrows[0]) {
    edge.arrows[0].rotation.z = Math.atan2(tip.y - beforeTip.y, tip.x - beforeTip.x) - Math.PI / 2;
  }
  if (edge.arrows[1]) {
    const start = points[0];
    const afterStart = points[1] || start;
    edge.arrows[1].position.copy(start);
    edge.arrows[1].rotation.z =
      Math.atan2(start.y - afterStart.y, start.x - afterStart.x) - Math.PI / 2;
  }
  positionEdgeLabel(edge, points);
}

/** Move a node within its own plane and refresh everything attached to it. */
export function moveNode(registry, nodeId, x, y) {
  const node = registry.nodes.get(nodeId);
  if (!node) return;
  const dx = x - node.local.x;
  const dy = y - node.local.y;
  node.local.set(x, y, node.local.z);
  for (const part of node.parts) {
    part.position.x += dx;
    part.position.y += dy;
  }
  for (const edge of registry.edgesByNode.get(nodeId) || []) refreshEdge(registry, edge);
}

/**
 * Apply an opacity multiplier to one object, relative to the opacity it was
 * built with. Every mesh records `baseOpacity` so repeated dimming passes never
 * compound.
 */
export function setPartOpacity(object, factor) {
  const material = object.material;
  if (!material || Array.isArray(material)) return;
  const base = object.userData.baseOpacity ?? 1;
  material.opacity = base * factor;
}

export function setNodeOpacity(node, factor) {
  for (const part of node.parts) setPartOpacity(part, factor);
}

export function setEdgeOpacity(edge, factor) {
  setPartOpacity(edge.line, factor);
  for (const arrow of edge.arrows) setPartOpacity(arrow, factor);
}

/** Vector3 in the group's local space; callers convert with the group matrix. */
export function localPosition(x, y, z = 0) {
  return new THREE.Vector3(x, y, z);
}
