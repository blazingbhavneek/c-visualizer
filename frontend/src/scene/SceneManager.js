import * as THREE from "three";
import CanvasControls from "./CanvasControls.js";
import { buildOverviewLayer } from "./buildOverview.js";
import { buildProcessPlaneLayer } from "./buildProcessPlane.js";
import { disposeObject } from "./primitives.js";
import { COLORS, SURFACE, processColor } from "./palette.js";
import { directPlanePairs } from "../graph/model.js";
import {
  EDGE_CATEGORIES,
  moveNode,
  setEdgeOpacity,
  setNodeOpacity,
  setPartOpacity,
} from "./graphLayer.js";
import {
  createRelaxation,
  isSettling,
  relaxStep,
  releasePin,
  resetToHome,
  setPinned,
} from "./relaxation.js";

const UP = new THREE.Vector3(0, 1, 0);
const MAX_OPEN_PLANES = 2;
/**
 * Labels appear only inside this radius. A 120-node tree framed whole is a wall
 * of overlapping text, so the tree reads as shape at distance and as names once
 * the camera moves in.
 */
const LABEL_DISTANCE = 950;
/**
 * Call trees are laid out at their natural size (2000-3900 units wide), which
 * is as large as the entire ground overview. Planes are scaled to this width so
 * a raised tree stays proportionate to the plane it grows from.
 */
const PLANE_TARGET_WIDTH = 2400;
/** Floor for the gap between the two process anchors when both planes are open. */
const MIN_FACING_SEPARATION = 2200;

/** While a process plane is active the ground recedes; edges more than nodes. */
const GROUND_NODE_FADE = 0.38;
const GROUND_EDGE_FADE = 0.1;
/** Everything not connected to the hovered node. */
const HOVER_DIM = 0.12;

/**
 * Flat drawings arranged in 3D.
 *
 * The ground plane holds the process/resource overview. Expanding a process
 * raises a vertical plane from that process's ground node holding its full call
 * tree. Nothing is drawn with depth *inside* a plane; the only true 3D geometry
 * is the set of edges that cross from one plane to another.
 */
export default class SceneManager {
  constructor(container, { onSelect, onHover, onPlanesChanged } = {}) {
    this.container = container;
    this.onSelect = onSelect || (() => {});
    this.onHover = onHover || (() => {});
    this.onPlanesChanged = onPlanesChanged || (() => {});

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(SURFACE);
    this.scene.fog = new THREE.Fog(SURFACE, 4200, 13000);

    this.camera = new THREE.PerspectiveCamera(52, 1, 1, 40000);
    this.camera.position.set(0, 2600, 2600);

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setClearColor(SURFACE, 1);
    container.appendChild(this.renderer.domElement);

    this.controls = new CanvasControls(this.camera, this.renderer.domElement);
    this.controls.minDistance = 60;
    this.controls.maxDistance = 22000;

    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();

    this.overviewLayer = null;
    this.overview = null;
    this.overviewLayout = null;
    this.planes = new Map(); // processName -> plane record, insertion order = FIFO
    this.crossPlaneGroup = new THREE.Group();
    this.scene.add(this.crossPlaneGroup);
    this.crossPlaneEdges = [];

    /**
     * In process view the tree is the subject, so daemon links start hidden and
     * the user opts in to seeing which function touches which resource.
     */
    this.edgeVisibility = {
      [EDGE_CATEGORIES.CALL]: true,
      [EDGE_CATEGORIES.INTERACTION]: false,
      [EDGE_CATEGORIES.GROUND]: true,
      [EDGE_CATEGORIES.PLANE_TO_PLANE]: true,
    };
    this.hoverHighlightEnabled = true;

    this.selected = null;
    this.hoveredNode = null;
    this.hoveredKey = null;
    this.focusedPlane = null;
    this.activeCanvas = "overview";
    this.drag = null;
    this.lastCameraPosition = new THREE.Vector3(Infinity, Infinity, Infinity);
    this.needsCrossPlaneRebuild = false;
    this.stylingDirty = true;
    this.disposed = false;

    this._onResize = this._handleResize.bind(this);
    this._onPointerMove = this._handlePointerMove.bind(this);
    this._onPointerDown = this._handlePointerDown.bind(this);
    this._onPointerUp = this._handlePointerUp.bind(this);

    window.addEventListener("resize", this._onResize);
    const element = this.renderer.domElement;
    // Capture phase so a node drag can claim the pointer before the camera
    // controls interpret the same gesture as a pan.
    element.addEventListener("pointerdown", this._onPointerDown, true);
    element.addEventListener("pointermove", this._onPointerMove);
    element.addEventListener("pointerup", this._onPointerUp, true);

    this._handleResize();
    this._animate();

    // Debug handle: the scene is otherwise unreachable from the console, and
    // picking/geometry problems are impossible to diagnose from the DOM alone.
    window.__viz = this;
  }

  // ---------------------------------------------------------------- overview

  setOverview(overview, overviewLayout) {
    this.overview = overview;
    this.overviewLayout = overviewLayout;
    this._rebuildOverview();
    this.frameOverview({ snap: true });
  }

  _rebuildOverview() {
    if (!this.overview) return;
    // Preserve any positions the user, or the facing arrangement, has moved.
    const kept = new Map();
    if (this.overviewLayer) {
      for (const [id, node] of this.overviewLayer.registry.nodes) kept.set(id, node.local.clone());
      this.scene.remove(this.overviewLayer.group);
      disposeObject(this.overviewLayer.group);
    }

    this.overviewLayer = buildOverviewLayer(this.overview, this.overviewLayout, {
      expandedProcesses: new Set(this.planes.keys()),
    });
    for (const [id, local] of kept) {
      if (this.overviewLayer.registry.nodes.has(id)) {
        moveNode(this.overviewLayer.registry, id, local.x, local.y);
      }
    }
    this.scene.add(this.overviewLayer.group);
    this.overviewLayer.group.updateMatrixWorld(true);
    this.stylingDirty = true;
  }

  /**
   * The ground plane as the active canvas: a plain top-down 2D view of the
   * overview, panned and zoomed like any flat graph canvas.
   */
  frameOverview({ snap = false } = {}) {
    if (!this.overviewLayer) return;
    let radius = 600;
    for (const node of this.overviewLayer.registry.nodes.values()) {
      radius = Math.max(radius, Math.hypot(node.local.x, node.local.y));
    }
    this.activeCanvas = "overview";
    this.stylingDirty = true;
    this.controls.setFrame(
      {
        origin: new THREE.Vector3(0, 0, 0),
        // Local +y of the overview drawing maps to world -z, so screen-up is -z
        // and the canvas reads exactly as it was laid out.
        right: new THREE.Vector3(1, 0, 0),
        up: new THREE.Vector3(0, 0, -1),
        normal: new THREE.Vector3(0, 1, 0),
      },
      { distance: this.controls.distanceToFit(radius * 2.2, radius * 2.2), snap },
    );
  }

  // ------------------------------------------------------------------ planes

  _overviewNodeWorld(id) {
    const node = this.overviewLayer?.registry.nodes.get(id);
    if (!node) return null;
    return node.local.clone().applyMatrix4(this.overviewLayer.group.matrixWorld);
  }

  _processAnchor(processName) {
    return this._overviewNodeWorld(`process:${processName}`) || new THREE.Vector3();
  }

  /**
   * Orientation for a single raised plane, taken from how the user is currently
   * looking rather than from an orbit angle. "Screen-down, flattened onto the
   * ground" means a raised tree comes up toward the viewer and reads
   * left-to-right exactly as the overview under it did.
   */
  _viewOrientation() {
    const normal = this.camera.up.clone().negate();
    normal.y = 0;
    if (normal.lengthSq() < 1e-6) {
      this.camera.getWorldDirection(normal);
      normal.y = 0;
      normal.negate();
    }
    if (normal.lengthSq() < 1e-6) normal.set(0, 0, 1);
    normal.normalize();
    return { right: new THREE.Vector3().crossVectors(UP, normal).normalize(), normal };
  }

  static _quaternionFor({ right, normal }) {
    return new THREE.Quaternion().setFromRotationMatrix(
      new THREE.Matrix4().makeBasis(right, UP, normal),
    );
  }

  openProcess(prepared, processIndexById) {
    if (!prepared) return;
    const { processName } = prepared;
    if (this.planes.has(processName)) {
      this.focusPlane(processName);
      return;
    }

    // FIFO: opening a third collapses the oldest.
    while (this.planes.size >= MAX_OPEN_PLANES) {
      this._removePlane(this.planes.keys().next().value);
    }

    const tint = processColor(processIndexById.get(processName) ?? 0);
    const layer = buildProcessPlaneLayer({
      treeNodes: prepared.treeNodes,
      treeLayout: prepared.treeLayout,
      shelf: prepared.shelf,
      portNames: prepared.portNames,
      entryFunctionId: prepared.entryFunctionId,
      processTint: tint,
      coverage: prepared.coverage,
      processName,
    });

    const width = Math.max(1, layer.bounds.maxX - layer.bounds.minX);
    layer.group.scale.setScalar(Math.min(1, PLANE_TARGET_WIDTH / width));
    layer.group.position.copy(this._processAnchor(processName));
    layer.group.quaternion.copy(SceneManager._quaternionFor(this._viewOrientation()));

    this.scene.add(layer.group);
    this.planes.set(processName, {
      processName,
      prepared,
      layer,
      tint,
      targetQuaternion: layer.group.quaternion.clone(),
      animating: false,
    });

    this.focusedPlane = processName;
    this._rebuildOverview();
    this._arrangePlanes();
    this.onPlanesChanged([...this.planes.keys()]);
  }

  /**
   * With one plane open it simply faces the viewer.
   *
   * With two, they become facing walls: the two process nodes are pushed apart
   * on the ground, each plane's normal points at the other, and the camera
   * stands between them. The user turns their head to read either tree, instead
   * of two parallel planes competing for the same pixels.
   */
  _arrangePlanes() {
    const open = [...this.planes.values()];

    if (open.length === 0) {
      this.frameOverview();
      return;
    }

    if (open.length === 1) {
      const plane = open[0];
      plane.targetQuaternion = SceneManager._quaternionFor(this._viewOrientation());
      plane.animating = true;
      plane.layer.group.position.copy(this._processAnchor(plane.processName));
      this.needsCrossPlaneRebuild = true;
      this.focusPlane(plane.processName);
      return;
    }

    const [a, b] = open;
    const registry = this.overviewLayer.registry;
    const nodeA = registry.nodes.get(`process:${a.processName}`);
    const nodeB = registry.nodes.get(`process:${b.processName}`);
    if (!nodeA || !nodeB) return;

    // Push the two anchors apart along the line already between them, keeping
    // their midpoint, so the rest of the ground layout stays recognisable.
    const midX = (nodeA.local.x + nodeB.local.x) / 2;
    const midY = (nodeA.local.y + nodeB.local.y) / 2;
    let axisX = nodeB.local.x - nodeA.local.x;
    let axisY = nodeB.local.y - nodeA.local.y;
    const axisLength = Math.hypot(axisX, axisY);
    if (axisLength < 1e-3) {
      axisX = 1;
      axisY = 0;
    } else {
      axisX /= axisLength;
      axisY /= axisLength;
    }
    // The camera stands at the midpoint, so half the gap is its viewing distance
    // to each plane. Derive it from what it takes to frame the wider tree,
    // otherwise the trees are cropped the moment they face each other.
    const separation = Math.max(
      MIN_FACING_SEPARATION,
      2 * Math.max(this._planeFitDistance(a), this._planeFitDistance(b)),
    );
    const half = separation / 2;
    moveNode(registry, nodeA.id, midX - axisX * half, midY - axisY * half);
    moveNode(registry, nodeB.id, midX + axisX * half, midY + axisY * half);

    const worldA = this._overviewNodeWorld(nodeA.id);
    const worldB = this._overviewNodeWorld(nodeB.id);
    a.layer.group.position.copy(worldA);
    b.layer.group.position.copy(worldB);

    // Each normal points at the other plane, so both fronts face the gap.
    const toB = worldB.clone().sub(worldA);
    toB.y = 0;
    toB.normalize();
    const toA = toB.clone().negate();

    a.targetQuaternion = SceneManager._quaternionFor({
      right: new THREE.Vector3().crossVectors(UP, toB).normalize(),
      normal: toB,
    });
    b.targetQuaternion = SceneManager._quaternionFor({
      right: new THREE.Vector3().crossVectors(UP, toA).normalize(),
      normal: toA,
    });
    a.animating = true;
    b.animating = true;

    // Stand between them at roughly tree height, looking at the focused one.
    const centre = worldA.clone().add(worldB).multiplyScalar(0.5);
    centre.y = this._planeEyeHeight(a);
    this.activeCanvas = "facing";
    this.controls.setPivot(centre, [toA.clone(), toB.clone()], { distance: half });
    this.lookAtPlane(this.focusedPlane || a.processName);

    this.stylingDirty = true;
    this.needsCrossPlaneRebuild = true;
  }

  /** Distance at which this plane's tree fills the view. */
  _planeFitDistance(plane) {
    const bounds = plane.prepared.treeLayout.bounds;
    const scale = plane.layer.group.scale.x;
    return this.controls.distanceToFit(
      (bounds.maxX - bounds.minX) * scale,
      (bounds.maxY - bounds.minY) * scale,
    );
  }

  _planeEyeHeight(plane) {
    const bounds = plane.prepared.treeLayout.bounds;
    return Math.max(120, ((bounds.minY + bounds.maxY) / 2) * plane.layer.group.scale.y);
  }

  /** Swing the head toward one of the two facing planes. */
  lookAtPlane(processName) {
    const plane = this.planes.get(processName);
    if (!plane || this.controls.mode !== "pivot") return;
    this.focusedPlane = processName;
    this.stylingDirty = true;
    const direction = plane.layer.group.position.clone().sub(this.controls.pivotOrigin);
    direction.y = 0;
    if (direction.lengthSq() > 1e-6) this.controls.lookAlong(direction.normalize());
  }

  _removePlane(processName) {
    const plane = this.planes.get(processName);
    if (!plane) return;
    this.scene.remove(plane.layer.group);
    disposeObject(plane.layer.group);
    this.planes.delete(processName);
    this.stylingDirty = true;
    if (this.focusedPlane === processName) {
      this.focusedPlane = this.planes.size ? [...this.planes.keys()].pop() : null;
    }
  }

  closeProcess(processName) {
    this._removePlane(processName);
    this._rebuildOverview();
    this.needsCrossPlaneRebuild = true;
    this.onPlanesChanged([...this.planes.keys()]);
    this._arrangePlanes();
  }

  collapseAll() {
    for (const processName of [...this.planes.keys()]) this._removePlane(processName);
    this.focusedPlane = null;
    this._rebuildOverview();
    this.needsCrossPlaneRebuild = true;
    this.onPlanesChanged([]);
    this.frameOverview();
  }

  focusPlane(processName) {
    const plane = this.planes.get(processName);
    if (!plane) return;
    this.focusedPlane = processName;
    this.stylingDirty = true;

    if (this.controls.mode === "pivot" && this.planes.size === 2) {
      this.lookAtPlane(processName);
      return;
    }

    // Frame the tree, not the unreached shelf: the shelf can be wider than the
    // tree and framing both would push the tree off to one side and far away.
    const bounds = plane.prepared.treeLayout.bounds;
    const scale = plane.layer.group.scale.x;
    const quaternion = plane.targetQuaternion || plane.layer.group.quaternion;

    const centre = new THREE.Vector3(
      (bounds.minX + bounds.maxX) / 2,
      (bounds.minY + bounds.maxY) / 2,
      0,
    )
      .multiplyScalar(scale)
      .applyQuaternion(quaternion)
      .add(plane.layer.group.position);

    this.activeCanvas = processName;
    this.controls.setFrame(
      {
        origin: centre,
        right: new THREE.Vector3(1, 0, 0).applyQuaternion(quaternion),
        up: new THREE.Vector3(0, 1, 0).applyQuaternion(quaternion),
        normal: new THREE.Vector3(0, 0, 1).applyQuaternion(quaternion),
      },
      {
        distance: this.controls.distanceToFit(
          (bounds.maxX - bounds.minX) * scale,
          (bounds.maxY - bounds.minY) * scale,
        ),
      },
    );
  }

  // ------------------------------------------------------- cross-plane edges

  _portWorldPositions(plane, attachment) {
    const nodes = attachment.portNodes.length ? attachment.portNodes : attachment.callerNodes;
    const positions = [];
    for (const node of nodes) {
      const entry = plane.layer.registry.nodes.get(node.uid);
      if (!entry) continue;
      positions.push(entry.local.clone().applyMatrix4(plane.layer.group.matrixWorld));
    }
    return positions;
  }

  _rebuildCrossPlaneEdges() {
    disposeObject(this.crossPlaneGroup);
    this.crossPlaneGroup.clear();
    this.crossPlaneEdges = [];
    if (this.planes.size === 0) return;

    for (const plane of this.planes.values()) plane.layer.group.updateMatrixWorld(true);
    this.overviewLayer?.group.updateMatrixWorld(true);

    // Function/port -> daemon resource on the ground plane.
    if (this.edgeVisibility[EDGE_CATEGORIES.INTERACTION] !== false) {
      for (const plane of this.planes.values()) {
        for (const attachment of plane.prepared.attachments) {
          const target = this._overviewNodeWorld(`resource:${attachment.resourceKey}`);
          if (!target) continue;
          for (const origin of this._portWorldPositions(plane, attachment)) {
            const forward = attachment.direction !== "in";
            this._addCrossPlaneEdge({
              from: forward ? origin : target,
              to: forward ? target : origin,
              color: COLORS.crossPlane,
              opacity: 0.34,
              category: EDGE_CATEGORIES.INTERACTION,
              processName: plane.processName,
            });
          }
        }
      }
    }

    // Plane-to-plane: producer/consumer pairs that meet on the same resource.
    const open = [...this.planes.values()];
    if (open.length === 2 && this.edgeVisibility[EDGE_CATEGORIES.PLANE_TO_PLANE] !== false) {
      const pairs = directPlanePairs(open[0].prepared.attachments, open[1].prepared.attachments);
      for (const pair of pairs) {
        const producerPlane = open[0].prepared.attachments.includes(pair.producer)
          ? open[0]
          : open[1];
        const consumerPlane = producerPlane === open[0] ? open[1] : open[0];
        for (const start of this._portWorldPositions(producerPlane, pair.producer)) {
          for (const end of this._portWorldPositions(consumerPlane, pair.consumer)) {
            this._addCrossPlaneEdge({
              from: start,
              to: end,
              color: COLORS.planeToPlane,
              opacity: 0.5,
              category: EDGE_CATEGORIES.PLANE_TO_PLANE,
            });
          }
        }
      }
    }
    this.stylingDirty = true;
  }

  _addCrossPlaneEdge({ from, to, color, opacity, category, processName }) {
    const middle = from.clone().add(to).multiplyScalar(0.5);
    // Lift the control point so the line reads as leaving its plane rather than
    // as another in-plane edge.
    middle.y += Math.max(90, from.distanceTo(to) * 0.16);
    const curve = new THREE.QuadraticBezierCurve3(from, middle, to);
    const line = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(curve.getPoints(34)),
      new THREE.LineBasicMaterial({
        color: new THREE.Color(color),
        transparent: true,
        opacity,
        depthWrite: false,
        toneMapped: false,
      }),
    );
    line.renderOrder = 5;
    line.userData.baseOpacity = opacity;
    this.crossPlaneGroup.add(line);
    this.crossPlaneEdges.push({ line, category, processName });
  }

  // ----------------------------------------------------------- presentation

  /** Undo any dragging and put every graph back to its computed layout. */
  resetLayout() {
    for (const { layer } of this._layers()) {
      resetToHome(layer.registry);
      layer.simulation = null;
    }
    this.simulation = null;
    for (const plane of this.planes.values()) {
      plane.layer.group.position.copy(this._processAnchor(plane.processName));
    }
    this.needsCrossPlaneRebuild = true;
    this.stylingDirty = true;
  }

  setEdgeVisibility(category, visible) {
    this.edgeVisibility[category] = visible;
    if (category === EDGE_CATEGORIES.INTERACTION || category === EDGE_CATEGORIES.PLANE_TO_PLANE) {
      this.needsCrossPlaneRebuild = true;
    }
    this.stylingDirty = true;
  }

  setHoverHighlight(enabled) {
    this.hoverHighlightEnabled = enabled;
    if (!enabled) {
      this.hoveredNode = null;
      this.hoveredKey = null;
    }
    this.stylingDirty = true;
  }

  _layers() {
    const layers = [];
    if (this.overviewLayer) layers.push({ kind: "overview", layer: this.overviewLayer });
    for (const plane of this.planes.values()) {
      layers.push({ kind: "plane", layer: plane.layer, plane });
    }
    return layers;
  }

  /**
   * One pass that decides every mark's opacity.
   *
   * Three effects compose here rather than fighting each other: category
   * visibility, the recede applied to whatever is not the active canvas, and
   * the hover highlight. Running them together is what keeps the result
   * predictable — applied separately, each would stomp the last.
   */
  _applyStyling() {
    const inProcessView = this.activeCanvas !== "overview";
    const hover = this.hoverHighlightEnabled ? this.hoveredNode : null;

    for (const { kind, layer, plane } of this._layers()) {
      const isGround = kind === "overview";
      let nodeFactor = 1;
      let edgeFactor = 1;

      if (isGround && inProcessView) {
        // Edges fade harder than nodes: the long ground edges are the noise.
        nodeFactor = GROUND_NODE_FADE;
        edgeFactor = GROUND_EDGE_FADE;
      } else if (!isGround && this.planes.size === 2 && plane.processName !== this.focusedPlane) {
        nodeFactor = 0.5;
        edgeFactor = 0.3;
      }

      const hoverHere = hover && hover.layer === layer;
      const neighbours = hoverHere ? this._neighbourhood(layer, hover.nodeId) : null;

      for (const [id, node] of layer.registry.nodes) {
        const dimmed = neighbours && !neighbours.nodes.has(id);
        setNodeOpacity(node, dimmed ? nodeFactor * HOVER_DIM : nodeFactor);
      }

      for (const edge of layer.registry.edges) {
        const visible = this.edgeVisibility[edge.category] !== false;
        const highlighted = neighbours ? neighbours.edges.has(edge) : false;
        const dimmed = neighbours && !highlighted;

        edge.line.visible = visible;
        for (const arrow of edge.arrows) arrow.visible = visible;
        setEdgeOpacity(edge, dimmed ? edgeFactor * HOVER_DIM : edgeFactor);

        // Edge labels are the messiest thing on either plane, so they exist
        // only while their edge is picked out by hover.
        if (edge.label) {
          edge.label.visible = visible && highlighted;
          setPartOpacity(edge.label, 1);
        }
      }

      if (hoverHere) {
        // The hovered node keeps its own label whatever the distance rule says.
        const node = layer.registry.nodes.get(hover.nodeId);
        for (const part of node?.parts || []) if (part.userData.isLabel) part.visible = true;
      }
    }

    for (const edge of this.crossPlaneEdges) {
      const visible = this.edgeVisibility[edge.category] !== false;
      edge.line.visible = visible;
      setPartOpacity(edge.line, hover ? 0.25 : 1);
    }
  }

  /** The hovered node, the edges touching it, and the nodes at their far ends. */
  _neighbourhood(layer, nodeId) {
    const nodes = new Set([nodeId]);
    const edges = new Set();
    for (const edge of layer.registry.edgesByNode.get(nodeId) || []) {
      if (this.edgeVisibility[edge.category] === false) continue;
      edges.add(edge);
      nodes.add(edge.sourceId);
      nodes.add(edge.targetId);
    }
    return { nodes, edges };
  }

  // ----------------------------------------------------------------- picking

  _pickTargets() {
    const targets = [];
    if (this.overviewLayer) targets.push(...this.overviewLayer.pickables);
    for (const plane of this.planes.values()) targets.push(...plane.layer.pickables);
    return targets;
  }

  _intersect() {
    this.raycaster.setFromCamera(this.pointer, this.camera);
    return this.raycaster.intersectObjects(this._pickTargets(), false);
  }

  _updatePointer(event) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  }

  _layerFor(object) {
    let current = object;
    while (current) {
      if (this.overviewLayer && current === this.overviewLayer.group) return this.overviewLayer;
      for (const plane of this.planes.values()) {
        if (current === plane.layer.group) return plane.layer;
      }
      current = current.parent;
    }
    return null;
  }

  _handlePointerDown(event) {
    this._updatePointer(event);
    this.pointerDownAt = { x: event.clientX, y: event.clientY };
    if (event.button !== 0 || event.shiftKey) return;

    const hit = this._intersect()[0];
    const nodeId = hit?.object.userData.nodeId;
    if (!nodeId) return;
    const layer = this._layerFor(hit.object);
    const node = layer?.registry.nodes.get(nodeId);
    if (!node) return;

    // Drag happens in the node's own plane, so a node can never leave the
    // drawing it belongs to.
    const normal = new THREE.Vector3(0, 0, 1).applyQuaternion(
      layer.group.getWorldQuaternion(new THREE.Quaternion()),
    );
    const dragPlane = new THREE.Plane().setFromNormalAndCoplanarPoint(normal, hit.point);
    const point = new THREE.Vector3();
    this.raycaster.ray.intersectPlane(dragPlane, point);
    const local = layer.group.worldToLocal(point.clone());

    // Neighbours follow the dragged node elastically, so build (or reuse) the
    // relaxation for this layer.
    if (!layer.simulation) layer.simulation = createRelaxation(layer.registry);
    this.simulation = { layer, sim: layer.simulation };

    this.drag = {
      layer,
      nodeId,
      dragPlane,
      offset: new THREE.Vector2(node.local.x - local.x, node.local.y - local.y),
      moved: false,
      processName: node.processName,
    };
    // Stop the camera controls from also treating this gesture as a pan.
    event.stopPropagation();
  }

  _handlePointerMove(event) {
    this._updatePointer(event);

    if (this.drag) {
      this.raycaster.setFromCamera(this.pointer, this.camera);
      const point = new THREE.Vector3();
      if (this.raycaster.ray.intersectPlane(this.drag.dragPlane, point)) {
        const local = this.drag.layer.group.worldToLocal(point.clone());
        moveNode(
          this.drag.layer.registry,
          this.drag.nodeId,
          local.x + this.drag.offset.x,
          local.y + this.drag.offset.y,
        );
        this.drag.moved = true;
        // A dragged process node carries its raised plane with it.
        if (this.drag.processName && this.planes.has(this.drag.processName)) {
          this.planes
            .get(this.drag.processName)
            .layer.group.position.copy(this._processAnchor(this.drag.processName));
        }
        this.needsCrossPlaneRebuild = true;
      }
      return;
    }

    const hit = this._intersect()[0];
    const pick = hit?.object.userData.pick || null;
    const nodeId = hit?.object.userData.nodeId || null;
    const layer = hit ? this._layerFor(hit.object) : null;
    const key = nodeId && layer ? `${layer.group.name}:${nodeId}` : null;

    if (key !== this.hoveredKey) {
      this.hoveredKey = key;
      this.hoveredNode = key ? { layer, nodeId } : null;
      this.stylingDirty = true;
      this.renderer.domElement.style.cursor = pick ? "pointer" : "grab";
      this.onHover(pick);
    }
  }

  _handlePointerUp(event) {
    const downAt = this.pointerDownAt;
    this.pointerDownAt = null;

    if (this.drag) {
      const wasDrag = this.drag.moved;
      if (wasDrag && this.simulation?.layer === this.drag.layer) {
        releasePin(this.simulation.sim);
      }
      this.drag = null;
      // A drag that actually moved the node is not also a click.
      if (wasDrag) {
        event.stopPropagation();
        return;
      }
    }
    if (!downAt) return;
    const moved = Math.abs(event.clientX - downAt.x) + Math.abs(event.clientY - downAt.y);
    if (moved > 6) return;

    const hit = this._intersect()[0];
    const pick = hit?.object.userData.pick || null;
    if (pick?.type === "function" && pick.processName) {
      this.focusedPlane = pick.processName;
      this.stylingDirty = true;
    }
    this.setSelected(pick, hit?.object || null);
    this.onSelect(pick);
  }

  setSelected(pick, object = null) {
    if (this.selectionRing) {
      this.selectionRing.parent?.remove(this.selectionRing);
      this.selectionRing.geometry.dispose();
      this.selectionRing.material.dispose();
      this.selectionRing = null;
    }
    this.selected = pick;
    if (!object) return;

    const radius = object.scale.x * 1.75;
    this.selectionRing = new THREE.Mesh(
      new THREE.RingGeometry(radius * 0.9, radius, 44),
      new THREE.MeshBasicMaterial({
        color: new THREE.Color(COLORS.selection),
        transparent: true,
        opacity: 0.95,
        side: THREE.DoubleSide,
        depthWrite: false,
        toneMapped: false,
      }),
    );
    this.selectionRing.position.copy(object.position);
    this.selectionRing.renderOrder = 6;
    object.parent.add(this.selectionRing);
  }

  // ------------------------------------------------------------------- frame

  _updateLabelVisibility() {
    if (this.overviewLayer) {
      for (const label of this.overviewLayer.labels) label.visible = true;
    }
    const worldPosition = new THREE.Vector3();
    for (const plane of this.planes.values()) {
      for (const label of plane.layer.labels) {
        if (!label.userData.detailLabel) {
          label.visible = true;
          continue;
        }
        label.getWorldPosition(worldPosition);
        label.visible = this.camera.position.distanceTo(worldPosition) < LABEL_DISTANCE;
      }
    }
  }

  _animate() {
    if (this.disposed) return;
    this.frameHandle = requestAnimationFrame(() => this._animate());

    let animating = false;
    for (const plane of this.planes.values()) {
      if (!plane.animating) continue;
      plane.layer.group.quaternion.slerp(plane.targetQuaternion, 0.12);
      if (plane.layer.group.quaternion.angleTo(plane.targetQuaternion) < 0.002) {
        plane.layer.group.quaternion.copy(plane.targetQuaternion);
        plane.animating = false;
        this.needsCrossPlaneRebuild = true;
      } else {
        animating = true;
      }
    }

    // Elastic settling: driven while a drag is active and afterwards until the
    // graph runs out of energy, which is what makes the motion read as a graph
    // view rather than a node teleporting on its own.
    if (this.simulation) {
      const pinnedId = this.drag?.layer === this.simulation.layer ? this.drag.nodeId : null;
      if (pinnedId) setPinned(this.simulation.sim, pinnedId);
      if (pinnedId || isSettling(this.simulation.sim)) {
        relaxStep(this.simulation.sim, pinnedId);
        this.needsCrossPlaneRebuild = true;
      } else {
        this.simulation = null;
      }
    }

    this.controls.update();

    if (this.camera.position.distanceToSquared(this.lastCameraPosition) > 4) {
      this.lastCameraPosition.copy(this.camera.position);
      this._updateLabelVisibility();
      this.stylingDirty = true;
    }

    if (animating || this.needsCrossPlaneRebuild) {
      this._rebuildCrossPlaneEdges();
      this.needsCrossPlaneRebuild = animating;
    }

    if (this.stylingDirty) {
      this.stylingDirty = false;
      this._applyStyling();
    }

    this.renderer.render(this.scene, this.camera);
  }

  _handleResize() {
    const width = this.container.clientWidth || 1;
    const height = this.container.clientHeight || 1;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
  }

  dispose() {
    this.disposed = true;
    cancelAnimationFrame(this.frameHandle);
    window.removeEventListener("resize", this._onResize);
    const element = this.renderer.domElement;
    element.removeEventListener("pointerdown", this._onPointerDown, true);
    element.removeEventListener("pointermove", this._onPointerMove);
    element.removeEventListener("pointerup", this._onPointerUp, true);
    this.controls.dispose();
    disposeObject(this.scene);
    this.renderer.dispose();
    element.remove();
  }
}
