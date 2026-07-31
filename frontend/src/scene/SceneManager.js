import * as THREE from "three";
import CanvasControls from "./CanvasControls.js";
import { buildOverviewLayer } from "./buildOverview.js";
import { buildProcessPlaneLayer } from "./buildProcessPlane.js";
import { disposeObject } from "./primitives.js";
import { COLORS, SURFACE, processColor } from "./palette.js";
import { directPlanePairs } from "../graph/model.js";

const UP = new THREE.Vector3(0, 1, 0);
const MAX_OPEN_PLANES = 2;
/**
 * Labels appear only inside this radius. A 120-node tree framed whole is a wall
 * of overlapping text, so the tree reads as shape at distance and as names once
 * the camera moves in.
 */
const LABEL_DISTANCE = 950;
const FOREGROUND_OPACITY = 0.3;
/**
 * Call trees are laid out at their natural size (2000-3900 units wide), which
 * is as large as the entire ground overview. Planes are scaled to this width so
 * a raised tree stays proportionate to the plane it grows from.
 */
const PLANE_TARGET_WIDTH = 2400;

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
    // Fog on a white surface fades distant planes toward the paper rather than
    // into darkness, which is what keeps the inactive canvas recessive.
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

    this.selected = null;
    this.hovered = null;
    this.focusedPlane = null;
    this.lastCameraPosition = new THREE.Vector3(Infinity, Infinity, Infinity);
    this.needsCrossPlaneRebuild = false;
    this.disposed = false;

    this._onResize = this._handleResize.bind(this);
    this._onPointerMove = this._handlePointerMove.bind(this);
    this._onPointerDown = this._handlePointerDown.bind(this);
    this._onPointerUp = this._handlePointerUp.bind(this);

    window.addEventListener("resize", this._onResize);
    const element = this.renderer.domElement;
    element.addEventListener("pointermove", this._onPointerMove);
    element.addEventListener("pointerdown", this._onPointerDown);
    element.addEventListener("pointerup", this._onPointerUp);

    this._handleResize();
    this._animate();

    // Debug handle: the scene is otherwise unreachable from the console, and
    // picking/geometry problems are impossible to diagnose from the DOM alone.
    window.__viz = this;
  }

  // ---------------------------------------------------------------- overview

  setOverview(overview, overviewLayout) {
    if (this.overviewLayer) {
      this.scene.remove(this.overviewLayer.group);
      disposeObject(this.overviewLayer.group);
    }
    this.overview = overview;
    this.overviewLayout = overviewLayout;
    this._rebuildOverview();
    this.frameOverview({ snap: true });
  }

  _rebuildOverview() {
    if (!this.overview) return;
    if (this.overviewLayer) {
      this.scene.remove(this.overviewLayer.group);
      disposeObject(this.overviewLayer.group);
    }
    this.overviewLayer = buildOverviewLayer(this.overview, this.overviewLayout, {
      expandedProcesses: new Set(this.planes.keys()),
    });
    this.scene.add(this.overviewLayer.group);
    this.overviewLayer.group.updateMatrixWorld(true);
  }

  /**
   * The ground plane as the active canvas: a plain top-down 2D view of the
   * overview, panned and zoomed like any flat graph canvas.
   */
  frameOverview({ snap = false } = {}) {
    if (!this.overviewLayout) return;
    let radius = 600;
    for (const point of this.overviewLayout.positions.values()) {
      radius = Math.max(radius, Math.hypot(point.x, point.y));
    }
    this.activeCanvas = "overview";
    this.controls.setFrame(
      {
        origin: new THREE.Vector3(0, 0, 0),
        // Local +y of the overview drawing maps to world -z, so screen-up is -z
        // and the canvas reads exactly as it was laid out.
        right: new THREE.Vector3(1, 0, 0),
        up: new THREE.Vector3(0, 0, -1),
        normal: new THREE.Vector3(0, 1, 0),
      },
      { distance: this.controls.distanceToFit(radius * 2, radius * 2), snap },
    );
  }

  // ------------------------------------------------------------------ planes

  /** Ground-plane world position of a process node. */
  _processAnchor(processName) {
    if (!this.overviewLayer) return new THREE.Vector3();
    const local = this.overviewLayer.anchors.get(`process:${processName}`);
    if (!local) return new THREE.Vector3();
    return local.clone().applyMatrix4(this.overviewLayer.group.matrixWorld);
  }

  /**
   * Orientation for a plane about to be raised, taken from how the user is
   * currently looking rather than from an orbit angle.
   *
   * "Screen-down, flattened onto the ground" is the direction the plane should
   * face. From the opening top-down canvas that is the bottom edge of the
   * screen, so a raised tree comes up toward the viewer and reads left-to-right
   * exactly as the overview under it did. From a tilted view it still resolves
   * to the horizontal direction pointing back at the viewer.
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
    const right = new THREE.Vector3().crossVectors(UP, normal).normalize();
    return { right, normal };
  }

  static _quaternionFor({ right, normal }) {
    const matrix = new THREE.Matrix4().makeBasis(right, UP, normal);
    return new THREE.Quaternion().setFromRotationMatrix(matrix);
  }

  openProcess(prepared, processIndexById) {
    if (!prepared) return;
    const { processName } = prepared;
    if (this.planes.has(processName)) {
      this.focusedPlane = processName;
      return;
    }

    // FIFO: opening a third collapses the oldest.
    while (this.planes.size >= MAX_OPEN_PLANES) {
      const oldest = this.planes.keys().next().value;
      this._removePlane(oldest);
    }

    const anchor = this._processAnchor(processName);
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

    layer.group.position.copy(anchor);
    const orientation = this._viewOrientation();
    layer.group.quaternion.copy(SceneManager._quaternionFor(orientation));

    const width = Math.max(1, layer.bounds.maxX - layer.bounds.minX);
    layer.group.scale.setScalar(Math.min(1, PLANE_TARGET_WIDTH / width));

    this.scene.add(layer.group);
    this.planes.set(processName, {
      processName,
      prepared,
      layer,
      anchor,
      tint,
      targetQuaternion: layer.group.quaternion.clone(),
      animating: false,
    });

    this.focusedPlane = processName;
    this._realignPlanes();
    this._rebuildOverview();
    this.needsCrossPlaneRebuild = true;
    this.onPlanesChanged([...this.planes.keys()]);
    // Expanding is a navigation act: move to face what was just raised.
    this.focusPlane(processName);
  }

  /**
   * With two planes open they must end up parallel and facing, so both animate
   * to one orientation derived from where the camera is now.
   */
  _realignPlanes() {
    if (this.planes.size < 2) {
      for (const plane of this.planes.values()) {
        plane.targetQuaternion = SceneManager._quaternionFor(this._viewOrientation());
        plane.animating = true;
      }
      return;
    }
    const shared = SceneManager._quaternionFor(this._viewOrientation());
    for (const plane of this.planes.values()) {
      plane.targetQuaternion = shared.clone();
      plane.animating = true;
    }
  }

  _removePlane(processName) {
    const plane = this.planes.get(processName);
    if (!plane) return;
    this.scene.remove(plane.layer.group);
    disposeObject(plane.layer.group);
    this.planes.delete(processName);
    this.fadeDirty = true;
    if (this.focusedPlane === processName) {
      this.focusedPlane = this.planes.size ? [...this.planes.keys()].pop() : null;
    }
  }

  closeProcess(processName) {
    const wasActive = this.activeCanvas === processName;
    this._removePlane(processName);
    this._realignPlanes();
    this._rebuildOverview();
    this.needsCrossPlaneRebuild = true;
    this.onPlanesChanged([...this.planes.keys()]);
    // The active canvas cannot be a plane that no longer exists: fall back to
    // the remaining plane, or all the way down to the ground.
    if (wasActive) {
      const remaining = [...this.planes.keys()].pop();
      if (remaining) this.focusPlane(remaining);
      else this.frameOverview();
    }
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
    this.fadeDirty = true;

    // Frame the tree, not the unreached shelf: the shelf can be wider than the
    // tree and framing both would push the tree off to one side and far away.
    const bounds = plane.prepared.treeLayout.bounds;
    const scale = plane.layer.group.scale.x;
    const quaternion = plane.targetQuaternion || plane.layer.group.quaternion;

    const center = new THREE.Vector3(
      (bounds.minX + bounds.maxX) / 2,
      (bounds.minY + bounds.maxY) / 2,
      0,
    )
      .multiplyScalar(scale)
      .applyQuaternion(quaternion)
      .add(plane.layer.group.position);

    const width = (bounds.maxX - bounds.minX) * scale;
    const height = (bounds.maxY - bounds.minY) * scale;

    // Hand the plane to the controls as the new canvas. Its basis is the
    // plane's own axes, so panning now slides along the tree and the wheel
    // dollies straight into it.
    this.activeCanvas = processName;
    this.controls.setFrame(
      {
        origin: center,
        right: new THREE.Vector3(1, 0, 0).applyQuaternion(quaternion),
        up: new THREE.Vector3(0, 1, 0).applyQuaternion(quaternion),
        normal: new THREE.Vector3(0, 0, 1).applyQuaternion(quaternion),
      },
      { distance: this.controls.distanceToFit(width, height) },
    );
  }

  // ------------------------------------------------------- cross-plane edges

  _portWorldPositions(plane, attachment) {
    const nodes = attachment.portNodes.length ? attachment.portNodes : attachment.callerNodes;
    const positions = [];
    for (const node of nodes) {
      const local = plane.layer.nodeAnchors.get(node.uid);
      if (!local) continue;
      positions.push(local.clone().applyMatrix4(plane.layer.group.matrixWorld));
    }
    return positions;
  }

  _resourceWorldPosition(resourceKey) {
    if (!this.overviewLayer) return null;
    const local = this.overviewLayer.anchors.get(`resource:${resourceKey}`);
    if (!local) return null;
    return local.clone().applyMatrix4(this.overviewLayer.group.matrixWorld);
  }

  _rebuildCrossPlaneEdges() {
    disposeObject(this.crossPlaneGroup);
    this.crossPlaneGroup.clear();
    if (this.planes.size === 0) return;

    for (const plane of this.planes.values()) {
      plane.layer.group.updateMatrixWorld(true);
    }
    if (this.overviewLayer) this.overviewLayer.group.updateMatrixWorld(true);

    // Function/port -> daemon resource on the ground plane.
    for (const plane of this.planes.values()) {
      for (const attachment of plane.prepared.attachments) {
        const target = this._resourceWorldPosition(attachment.resourceKey);
        if (!target) continue;
        for (const origin of this._portWorldPositions(plane, attachment)) {
          const forward = attachment.direction !== "in";
          this.crossPlaneGroup.add(
            this._curve(forward ? origin : target, forward ? target : origin, COLORS.crossPlane, 0.34),
          );
        }
      }
    }

    // Plane-to-plane: producer/consumer pairs that meet on the same resource.
    const open = [...this.planes.values()];
    if (open.length === 2) {
      const pairs = directPlanePairs(open[0].prepared.attachments, open[1].prepared.attachments);
      for (const pair of pairs) {
        const producerPlane = open[0].prepared.attachments.includes(pair.producer) ? open[0] : open[1];
        const consumerPlane = producerPlane === open[0] ? open[1] : open[0];
        const from = this._portWorldPositions(producerPlane, pair.producer);
        const to = this._portWorldPositions(consumerPlane, pair.consumer);
        for (const start of from) {
          for (const end of to) {
            this.crossPlaneGroup.add(this._curve(start, end, COLORS.planeToPlane, 0.5));
          }
        }
      }
    }
  }

  _curve(from, to, color, opacity) {
    const middle = from.clone().add(to).multiplyScalar(0.5);
    // Lift the control point so the line reads as leaving its plane rather than
    // as another in-plane edge.
    middle.y += Math.max(90, from.distanceTo(to) * 0.16);
    const curve = new THREE.QuadraticBezierCurve3(from, middle, to);
    const geometry = new THREE.BufferGeometry().setFromPoints(curve.getPoints(34));
    const material = new THREE.LineBasicMaterial({
      color: new THREE.Color(color),
      transparent: true,
      opacity,
      depthWrite: false,
      toneMapped: false,
    });
    const line = new THREE.Line(geometry, material);
    line.renderOrder = 5;
    return line;
  }

  // ----------------------------------------------------------------- picking

  _pickablesUnderPointer() {
    const targets = [];
    if (this.overviewLayer) targets.push(...this.overviewLayer.pickables);
    for (const plane of this.planes.values()) targets.push(...plane.layer.pickables);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    return this.raycaster.intersectObjects(targets, false);
  }

  _handlePointerMove(event) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

    const hit = this._pickablesUnderPointer()[0];
    const pick = hit?.object.userData.pick || null;
    const key = pick ? JSON.stringify([pick.type, pick.node?.uid, pick.process?.name, pick.resource?.key]) : null;
    if (key !== this.hoveredKey) {
      this.hoveredKey = key;
      this.hovered = hit?.object || null;
      this.renderer.domElement.style.cursor = pick ? "pointer" : "grab";
      this.onHover(pick);
    }
  }

  _handlePointerDown(event) {
    this.pointerDownAt = { x: event.clientX, y: event.clientY };
  }

  _handlePointerUp(event) {
    if (!this.pointerDownAt) return;
    const moved =
      Math.abs(event.clientX - this.pointerDownAt.x) + Math.abs(event.clientY - this.pointerDownAt.y);
    this.pointerDownAt = null;
    // Ignore the pointerup that ends an orbit/pan drag.
    if (moved > 6) return;

    const hit = this._pickablesUnderPointer()[0];
    const pick = hit?.object.userData.pick || null;
    if (pick?.type === "function" && pick.processName) {
      this.focusedPlane = pick.processName;
      this.fadeDirty = true;
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
    const geometry = new THREE.RingGeometry(radius * 0.9, radius, 44);
    const material = new THREE.MeshBasicMaterial({
      color: new THREE.Color(COLORS.selection),
      transparent: true,
      opacity: 0.95,
      side: THREE.DoubleSide,
      depthWrite: false,
      toneMapped: false,
    });
    this.selectionRing = new THREE.Mesh(geometry, material);
    this.selectionRing.position.copy(object.position);
    this.selectionRing.renderOrder = 6;
    object.parent.add(this.selectionRing);
  }

  // ------------------------------------------------------------------- frame

  _applyPlaneFade() {
    if (this.planes.size < 2) {
      for (const plane of this.planes.values()) setGroupOpacity(plane.layer.group, 1);
      return;
    }
    // Two parallel planes facing the same way overlap heavily on screen. Fading
    // whichever one is not focused is what keeps the other readable through it;
    // clicking a plane's chip or any node on it swaps which that is.
    for (const plane of this.planes.values()) {
      const focused = plane.processName === this.focusedPlane;
      setGroupOpacity(plane.layer.group, focused ? 1 : FOREGROUND_OPACITY);
    }
  }

  _updateLabelVisibility() {
    const cameraPosition = this.camera.position;
    const check = (group) => {
      for (const label of group.userData.labels || []) {
        label.visible = true;
      }
    };
    if (this.overviewLayer) check(this.overviewLayer.group);

    const worldPosition = new THREE.Vector3();
    for (const plane of this.planes.values()) {
      for (const label of plane.layer.labels) {
        if (!label.userData.detailLabel) {
          label.visible = true;
          continue;
        }
        label.getWorldPosition(worldPosition);
        label.visible = cameraPosition.distanceTo(worldPosition) < LABEL_DISTANCE;
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

    this.controls.update();

    const cameraMoved = this.camera.position.distanceToSquared(this.lastCameraPosition) > 4;
    if (cameraMoved) {
      this.lastCameraPosition.copy(this.camera.position);
      this._updateLabelVisibility();
    }
    // Focus changes without the camera moving, so fade has its own dirty flag.
    if (cameraMoved || this.fadeDirty) {
      this.fadeDirty = false;
      this._applyPlaneFade();
    }

    if (animating || this.needsCrossPlaneRebuild) {
      this._rebuildCrossPlaneEdges();
      this.needsCrossPlaneRebuild = animating;
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
    element.removeEventListener("pointermove", this._onPointerMove);
    element.removeEventListener("pointerdown", this._onPointerDown);
    element.removeEventListener("pointerup", this._onPointerUp);
    this.controls.dispose();
    disposeObject(this.scene);
    this.renderer.dispose();
    element.remove();
  }
}

/**
 * Fade an entire flat drawing. This is the "blur the foreground" behaviour:
 * a real depth-of-field blur needs a post-processing pass, so the readable
 * approximation is a uniform opacity drop on every material in the group.
 */
function setGroupOpacity(group, factor) {
  group.traverse((child) => {
    const material = child.material;
    if (!material || Array.isArray(material)) return;
    const base = child.userData.baseOpacity ?? 1;
    material.opacity = base * factor;
  });
}
