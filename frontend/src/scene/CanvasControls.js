import * as THREE from "three";

/**
 * Two camera modes, one gesture set.
 *
 * **canvas** — the default. Exactly one plane is "the canvas" and the camera is
 * locked to it: dragging pans parallel to that plane, the wheel dollies along
 * its normal, screen-up is the plane's up. Looking dead-on is the resting
 * state, so the active plane looks identical to the flat drawing it was laid
 * out as. Tilt is clamped to a shallow cone — enough to see which edges leave
 * the surface, never enough to get lost behind the graph.
 *
 * **pivot** — used when two process planes are open facing each other. The
 * camera stands between them and turns its head: dragging looks around, the
 * wheel walks forward and back along the current heading. Yaw is clamped to the
 * arc that spans the two planes plus a margin, so the user can sweep from one
 * tree to the other but never end up staring into empty space behind them.
 */

const MAX_YAW = THREE.MathUtils.degToRad(24);
const MAX_PITCH = THREE.MathUtils.degToRad(18);
const PIVOT_MAX_PITCH = THREE.MathUtils.degToRad(28);
const ROTATE_SPEED = 0.0042;
const LOOK_SPEED = 0.0032;
const ZOOM_SPEED = 0.0012;
const DAMPING = 0.14;
/** Fraction of the current tilt kept when the active canvas changes. */
const TILT_CARRYOVER = 0.25;

export default class CanvasControls {
  constructor(camera, domElement) {
    this.camera = camera;
    this.domElement = domElement;

    this.mode = "canvas";

    // The active canvas: an origin plus an orthonormal basis. `normal` points
    // at the viewer, `up` is screen-up, `right` is screen-right.
    this.frame = {
      origin: new THREE.Vector3(),
      right: new THREE.Vector3(1, 0, 0),
      up: new THREE.Vector3(0, 0, -1),
      normal: new THREE.Vector3(0, 1, 0),
    };

    this.pan = new THREE.Vector2(0, 0);
    this.distance = 2000;
    this.minDistance = 40;
    this.maxDistance = 40000;
    this.yaw = 0;
    this.pitch = 0;
    this.enabled = true;

    // pivot mode
    this.pivotOrigin = new THREE.Vector3();
    this.pivotHeading = 0;
    this.pivotYawLimit = Math.PI;
    this.pivotCenterYaw = 0;

    this._initialised = false;
    this._pointer = null;
    this._mode = null;
    this._last = new THREE.Vector2();

    this._smoothedPosition = new THREE.Vector3();
    this._smoothedTarget = new THREE.Vector3();
    this._smoothedUp = new THREE.Vector3(0, 1, 0);

    this._onPointerDown = this._handlePointerDown.bind(this);
    this._onPointerMove = this._handlePointerMove.bind(this);
    this._onPointerUp = this._handlePointerUp.bind(this);
    this._onWheel = this._handleWheel.bind(this);
    this._onContextMenu = (event) => event.preventDefault();

    domElement.addEventListener("pointerdown", this._onPointerDown);
    domElement.addEventListener("pointermove", this._onPointerMove);
    domElement.addEventListener("pointerup", this._onPointerUp);
    domElement.addEventListener("pointercancel", this._onPointerUp);
    domElement.addEventListener("wheel", this._onWheel, { passive: false });
    domElement.addEventListener("contextmenu", this._onContextMenu);
  }

  /** True while a node drag owns the pointer, so the camera must not react. */
  get isGesturing() {
    return this._pointer !== null;
  }

  // ----------------------------------------------------------- canvas mode

  setFrame(frame, { distance, pan = new THREE.Vector2(0, 0), snap = false } = {}) {
    this.mode = "canvas";
    this.frame = {
      origin: frame.origin.clone(),
      right: frame.right.clone().normalize(),
      up: frame.up.clone().normalize(),
      normal: frame.normal.clone().normalize(),
    };
    this.pan.copy(pan);
    if (distance != null) {
      this.distance = THREE.MathUtils.clamp(distance, this.minDistance, this.maxDistance);
    }

    // Land on the new canvas essentially straight-on: a canvas is meant to be
    // read flat, and carrying a full tilt across would drop the user onto a
    // skewed plane. A little is kept so cross-plane edges still read as leaving
    // the surface rather than lying on it.
    this.yaw *= TILT_CARRYOVER;
    this.pitch *= TILT_CARRYOVER;

    if (snap || !this._initialised) this._snap();
  }

  /** Distance at which a `width` x `height` region on the canvas fills the view. */
  distanceToFit(width, height, margin = 1.12) {
    const halfFov = (this.camera.fov * Math.PI) / 360;
    const vertical = height / 2 / Math.tan(halfFov);
    const horizontal = width / 2 / (Math.tan(halfFov) * this.camera.aspect);
    return Math.max(vertical, horizontal) * margin;
  }

  get target() {
    return this.frame.origin
      .clone()
      .addScaledVector(this.frame.right, this.pan.x)
      .addScaledVector(this.frame.up, this.pan.y);
  }

  // ------------------------------------------------------------ pivot mode

  /**
   * Stand at `origin` and look toward `headings[0]`. `headings` are world
   * directions (one per open plane); yaw is limited to the arc they span plus a
   * margin, so the sweep covers both trees and nothing else.
   */
  setPivot(origin, headings, { snap = false } = {}) {
    this.mode = "pivot";
    this.pivotOrigin.copy(origin);

    const angles = headings.map((direction) => Math.atan2(direction.x, direction.z));
    if (angles.length >= 2) {
      // Shortest arc between the two headings, then widen it a little.
      let delta = angles[1] - angles[0];
      while (delta > Math.PI) delta -= Math.PI * 2;
      while (delta < -Math.PI) delta += Math.PI * 2;
      this.pivotCenterYaw = angles[0] + delta / 2;
      this.pivotYawLimit = Math.abs(delta) / 2 + THREE.MathUtils.degToRad(20);
    } else {
      this.pivotCenterYaw = angles[0] ?? 0;
      this.pivotYawLimit = THREE.MathUtils.degToRad(50);
    }

    this.pivotHeading = angles[0] ?? 0;
    this.pitch *= TILT_CARRYOVER;
    if (snap || !this._initialised) this._snap();
  }

  /** Swing the head to face one of the pivot headings. */
  lookAlong(direction) {
    if (this.mode !== "pivot") return;
    this.pivotHeading = this._clampYaw(Math.atan2(direction.x, direction.z));
  }

  _clampYaw(angle) {
    let delta = angle - this.pivotCenterYaw;
    while (delta > Math.PI) delta -= Math.PI * 2;
    while (delta < -Math.PI) delta += Math.PI * 2;
    return this.pivotCenterYaw + THREE.MathUtils.clamp(delta, -this.pivotYawLimit, this.pivotYawLimit);
  }

  _pivotForward() {
    return new THREE.Vector3(
      Math.sin(this.pivotHeading) * Math.cos(this.pitch),
      Math.sin(this.pitch),
      Math.cos(this.pivotHeading) * Math.cos(this.pitch),
    ).normalize();
  }

  // ---------------------------------------------------------------- shared

  _tiltQuaternion() {
    const yaw = new THREE.Quaternion().setFromAxisAngle(this.frame.up, this.yaw);
    const pitchAxis = this.frame.right.clone().applyQuaternion(yaw);
    const pitch = new THREE.Quaternion().setFromAxisAngle(pitchAxis, this.pitch);
    return pitch.multiply(yaw);
  }

  _desired() {
    if (this.mode === "pivot") {
      const forward = this._pivotForward();
      const position = this.pivotOrigin.clone();
      return {
        position,
        target: position.clone().addScaledVector(forward, 1000),
        up: new THREE.Vector3(0, 1, 0),
      };
    }
    const tilt = this._tiltQuaternion();
    const direction = this.frame.normal.clone().applyQuaternion(tilt);
    const up = this.frame.up.clone().applyQuaternion(tilt);
    const target = this.target;
    return { position: target.clone().addScaledVector(direction, this.distance), target, up };
  }

  _snap() {
    this._initialised = true;
    const { position, target, up } = this._desired();
    this._smoothedPosition.copy(position);
    this._smoothedTarget.copy(target);
    this._smoothedUp.copy(up);
    this._apply();
  }

  _apply() {
    this.camera.position.copy(this._smoothedPosition);
    this.camera.up.copy(this._smoothedUp);
    this.camera.lookAt(this._smoothedTarget);
    this.camera.updateMatrixWorld();
  }

  update() {
    if (!this._initialised) return;
    const { position, target, up } = this._desired();
    this._smoothedPosition.lerp(position, DAMPING);
    this._smoothedTarget.lerp(target, DAMPING);
    this._smoothedUp.lerp(up, DAMPING).normalize();
    this._apply();
  }

  // ---------------------------------------------------------------- gestures

  _handlePointerDown(event) {
    if (!this.enabled || this._pointer !== null) return;
    this._pointer = event.pointerId;
    const secondary = event.button === 2 || event.button === 1 || event.shiftKey;
    // In pivot mode the primary gesture is looking around, not panning: the
    // whole point of standing between two planes is to turn your head.
    this._mode = this.mode === "pivot" ? (secondary ? "walk" : "look") : secondary ? "tilt" : "pan";
    this._last.set(event.clientX, event.clientY);
    this.domElement.setPointerCapture?.(event.pointerId);
  }

  _handlePointerMove(event) {
    if (this._pointer !== event.pointerId) return;
    const dx = event.clientX - this._last.x;
    const dy = event.clientY - this._last.y;
    this._last.set(event.clientX, event.clientY);

    if (this._mode === "look") {
      this.pivotHeading = this._clampYaw(this.pivotHeading + dx * LOOK_SPEED);
      this.pitch = THREE.MathUtils.clamp(
        this.pitch + dy * LOOK_SPEED,
        -PIVOT_MAX_PITCH,
        PIVOT_MAX_PITCH,
      );
      return;
    }

    if (this._mode === "walk") {
      const right = new THREE.Vector3(Math.cos(this.pivotHeading), 0, -Math.sin(this.pivotHeading));
      this.pivotOrigin.addScaledVector(right, -dx * 2.2);
      this.pivotOrigin.y = Math.max(40, this.pivotOrigin.y + dy * 2.2);
      return;
    }

    if (this._mode === "tilt") {
      this.yaw = THREE.MathUtils.clamp(this.yaw - dx * ROTATE_SPEED, -MAX_YAW, MAX_YAW);
      this.pitch = THREE.MathUtils.clamp(this.pitch + dy * ROTATE_SPEED, -MAX_PITCH, MAX_PITCH);
      return;
    }

    // Pan so the point under the cursor tracks it: at the canvas depth, one
    // pixel is this many world units.
    const height = this.domElement.clientHeight || 1;
    const perPixel = (2 * this.distance * Math.tan((this.camera.fov * Math.PI) / 360)) / height;
    this.pan.x -= dx * perPixel;
    this.pan.y += dy * perPixel;
  }

  _handlePointerUp(event) {
    if (this._pointer !== event.pointerId) return;
    this.domElement.releasePointerCapture?.(event.pointerId);
    this._pointer = null;
    this._mode = null;
  }

  _handleWheel(event) {
    if (!this.enabled) return;
    event.preventDefault();
    if (this.mode === "pivot") {
      // Walk along the current heading rather than scaling a radius.
      this.pivotOrigin.addScaledVector(this._pivotForward(), -event.deltaY * 1.1);
      return;
    }
    const factor = Math.exp(event.deltaY * ZOOM_SPEED);
    this.distance = THREE.MathUtils.clamp(
      this.distance * factor,
      this.minDistance,
      this.maxDistance,
    );
  }

  /** Return to looking dead-on at the active canvas. */
  resetTilt() {
    if (this.mode === "pivot") {
      this.pivotHeading = this.pivotCenterYaw;
      this.pitch = 0;
      return;
    }
    this.yaw = 0;
    this.pitch = 0;
  }

  get isTilted() {
    return Math.abs(this.yaw) > 1e-3 || Math.abs(this.pitch) > 1e-3;
  }

  dispose() {
    const element = this.domElement;
    element.removeEventListener("pointerdown", this._onPointerDown);
    element.removeEventListener("pointermove", this._onPointerMove);
    element.removeEventListener("pointerup", this._onPointerUp);
    element.removeEventListener("pointercancel", this._onPointerUp);
    element.removeEventListener("wheel", this._onWheel);
    element.removeEventListener("contextmenu", this._onContextMenu);
  }
}
