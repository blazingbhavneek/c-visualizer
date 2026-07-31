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
 * camera stands between them and turns its head. Yaw is clamped to the arc that
 * spans the two planes plus a margin, so the user can sweep from one tree to
 * the other but never end up staring into empty space behind them.
 *
 * The gesture mapping is identical in both modes, because switching it under
 * the user when a second plane opens is disorienting: **left-drag moves you**
 * (pan across the canvas, or strafe between the planes), **right-drag rotates**
 * (tilt, or turn the head), and the **wheel closes distance**. Pivot motion is
 * scaled by the distance to the plane being faced, so a drag covers the same
 * amount of screen there as it does on a flat canvas.
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
/**
 * Rotation is spring-loaded rather than free inside a hard wall.
 *
 * Turning away from the resting angle gets progressively heavier the further
 * out you are, turning back is easier than neutral, and letting go lets the
 * view drift home. The straight-on view of a plane is the one worth being in,
 * so it should take effort to leave and none to return.
 */
const RETURN_ASSIST = 1.4;
const MIN_RESISTANCE = 0.1;
/** Per-frame fraction of the remaining offset given back while idle. */
const RECENTER_CANVAS = 0.05;
const RECENTER_PIVOT = 0.03;
/** How much of the gap to a plane the viewer may cross when walking. */
const PIVOT_ADVANCE_LIMIT = 0.78;

/**
 * Move a rotation toward `delta`, resisting movement away from rest and
 * assisting movement back toward it.
 */
function resistedRotation(current, delta, limit, rest = 0) {
  const offset = current - rest;
  const movingAway = offset === 0 || Math.sign(delta) === Math.sign(offset);
  const ratio = Math.min(1, Math.abs(offset) / limit);
  const factor = movingAway ? Math.max(MIN_RESISTANCE, 1 - ratio * ratio) : RETURN_ASSIST;
  return THREE.MathUtils.clamp(offset + delta * factor, -limit, limit) + rest;
}

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
    /** Distance to the plane being faced; sets the scale of pivot gestures. */
    this.pivotDistance = 2000;
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
  setPivot(origin, headings, { distance, snap = false } = {}) {
    this.mode = "pivot";
    this.pivotOrigin.copy(origin);
    this.pivotCentre = origin.clone();
    this.pivotHeadings = headings.map((direction) => Math.atan2(direction.x, direction.z));
    // The corridor between the two planes. Walking, not rotating, is what used
    // to put the viewer behind a tree and show its back.
    this.pivotAxis = headings.length >= 2 ? headings[1].clone().normalize() : null;
    this.pivotSpan = distance ?? this.pivotDistance;
    if (distance != null) {
      this.pivotDistance = THREE.MathUtils.clamp(distance, this.minDistance, this.maxDistance);
    }

    const angles = headings.map((direction) => Math.atan2(direction.x, direction.z));
    if (angles.length >= 2) {
      // Shortest arc between the two headings, then widen it a little.
      let delta = angles[1] - angles[0];
      while (delta > Math.PI) delta -= Math.PI * 2;
      while (delta < -Math.PI) delta += Math.PI * 2;
      this.pivotCenterYaw = angles[0] + delta / 2;
      // Just enough past each plane to see it obliquely, not to get behind it.
      this.pivotYawLimit = Math.abs(delta) / 2 + THREE.MathUtils.degToRad(8);
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

  /** Keep the viewer inside the corridor between the two facing planes. */
  _clampPivotOrigin() {
    if (!this.pivotAxis || !this.pivotCentre) return;
    const offset = this.pivotOrigin.clone().sub(this.pivotCentre);
    const along = offset.dot(this.pivotAxis);
    const limit = this.pivotSpan * PIVOT_ADVANCE_LIMIT;
    if (Math.abs(along) > limit) {
      this.pivotOrigin.addScaledVector(this.pivotAxis, Math.sign(along) * limit - along);
    }
  }

  /** Heading of whichever plane the viewer is currently closest to facing. */
  _nearestHeading() {
    if (!this.pivotHeadings?.length) return this.pivotCenterYaw;
    let best = this.pivotHeadings[0];
    let bestDelta = Infinity;
    for (const heading of this.pivotHeadings) {
      let delta = heading - this.pivotHeading;
      while (delta > Math.PI) delta -= Math.PI * 2;
      while (delta < -Math.PI) delta += Math.PI * 2;
      if (Math.abs(delta) < bestDelta) {
        bestDelta = Math.abs(delta);
        best = this.pivotHeading + delta;
      }
    }
    return best;
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

  /**
   * Drift back toward the resting angle whenever the user is not rotating, so
   * the good viewing angle is where the camera ends up on its own.
   */
  _recenter() {
    if (this._mode === "tilt" || this._mode === "look") return;
    if (this.mode === "pivot") {
      this.pitch += -this.pitch * RECENTER_PIVOT;
      // Settle onto whichever tree is being looked at rather than between them.
      const heading = this._nearestHeading();
      this.pivotHeading += (heading - this.pivotHeading) * RECENTER_PIVOT;
      return;
    }
    this.yaw += -this.yaw * RECENTER_CANVAS;
    this.pitch += -this.pitch * RECENTER_CANVAS;
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
    this._recenter();
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
    // Same mapping in both modes: primary drag moves the viewer, secondary drag
    // rotates. Swapping these when a second plane opens is disorienting.
    this._mode = secondary
      ? this.mode === "pivot"
        ? "look"
        : "tilt"
      : this.mode === "pivot"
        ? "walk"
        : "pan";
    this._last.set(event.clientX, event.clientY);
    this.domElement.setPointerCapture?.(event.pointerId);
  }

  _handlePointerMove(event) {
    if (this._pointer !== event.pointerId) return;
    const dx = event.clientX - this._last.x;
    const dy = event.clientY - this._last.y;
    this._last.set(event.clientX, event.clientY);

    if (this._mode === "look") {
      this.pivotHeading = this._clampYaw(
        resistedRotation(this.pivotHeading, dx * LOOK_SPEED, this.pivotYawLimit, this._nearestHeading()),
      );
      this.pitch = resistedRotation(this.pitch, dy * LOOK_SPEED, PIVOT_MAX_PITCH);
      return;
    }

    if (this._mode === "walk") {
      // Same world-units-per-pixel rule as canvas panning, using the distance to
      // the plane being faced, so a drag covers the same amount of screen.
      const perPixel = this._perPixel(this.pivotDistance);
      const right = new THREE.Vector3(Math.cos(this.pivotHeading), 0, -Math.sin(this.pivotHeading));
      this.pivotOrigin.addScaledVector(right, -dx * perPixel);
      this.pivotOrigin.y = Math.max(40, this.pivotOrigin.y + dy * perPixel);
      this._clampPivotOrigin();
      return;
    }

    if (this._mode === "tilt") {
      this.yaw = resistedRotation(this.yaw, -dx * ROTATE_SPEED, MAX_YAW);
      this.pitch = resistedRotation(this.pitch, dy * ROTATE_SPEED, MAX_PITCH);
      return;
    }

    // Pan so the point under the cursor tracks it.
    const perPixel = this._perPixel(this.distance);
    this.pan.x -= dx * perPixel;
    this.pan.y += dy * perPixel;
  }

  /** World units covered by one pixel of drag at a given viewing distance. */
  _perPixel(distance) {
    const height = this.domElement.clientHeight || 1;
    return (2 * distance * Math.tan((this.camera.fov * Math.PI) / 360)) / height;
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
    const factor = Math.exp(event.deltaY * ZOOM_SPEED);
    if (this.mode === "pivot") {
      // Walk along the heading, closing a fraction of the remaining distance so
      // the wheel behaves like the dolly on a flat canvas rather than a fixed
      // step that crawls when far away and overshoots when close.
      const next = THREE.MathUtils.clamp(
        this.pivotDistance * factor,
        this.minDistance,
        this.maxDistance,
      );
      this.pivotOrigin.addScaledVector(this._pivotForward(), this.pivotDistance - next);
      this.pivotDistance = next;
      this._clampPivotOrigin();
      return;
    }
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
