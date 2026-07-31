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

/**
 * These are resistance *scales*, not walls. Rotation gets heavy around them but
 * never stops: a determined drag can carry the view all the way behind a tree.
 * Only pitch has a genuine limit, to keep the up-vector from inverting.
 */
const YAW_SCALE = THREE.MathUtils.degToRad(24);
const PITCH_SCALE = THREE.MathUtils.degToRad(18);
const HARD_PITCH = THREE.MathUtils.degToRad(85);
const PIVOT_PITCH_SCALE = THREE.MathUtils.degToRad(28);
const ROTATE_SPEED = 0.0042;
const LOOK_SPEED = 0.0032;
const ZOOM_SPEED = 0.0012;
const DAMPING = 0.14;
/** Fraction of the current tilt kept when the active canvas changes. */
const TILT_CARRYOVER = 0.25;
/**
 * Rotation is weighted, not fenced, and never moves on its own.
 *
 * Turning away from the straight-on view gets heavier the further out you are;
 * turning back is easier than neutral. The resistance is floored so continued
 * dragging always makes progress - swinging right around behind a tree is
 * roughly two full-width drags.
 *
 * The view does NOT drift home when released. An earlier version eased back to
 * dead-on automatically, which meant a hard-won angle evaporated the moment the
 * button came up. Where the user let go is where the camera stays; "Look
 * straight on" is the way back.
 */
const RETURN_ASSIST = 1.4;
const MIN_RESISTANCE = 0.22;
/**
 * The viewer never goes under the ground plane. Dipping below it flips the
 * overview on its back and mirrors everything, which reads as the whole scene
 * inverting. Rotation is for going around and over the ground, not under it.
 */
const MIN_CAMERA_HEIGHT = 80;
/** How fast look resistance builds once the head turns outside the arc. */
const PIVOT_LOOK_SCALE = THREE.MathUtils.degToRad(30);
/** How much of the gap to a plane the viewer may cross when walking. */
const PIVOT_ADVANCE_LIMIT = 0.78;

/**
 * Move a rotation toward `delta`, resisting movement away from rest and
 * assisting movement back toward it.
 */
function resistedRotation(current, delta, scale, { rest = 0, hardLimit = Infinity } = {}) {
  const offset = current - rest;
  const movingAway = offset === 0 || Math.sign(delta) === Math.sign(offset);
  const ratio = Math.abs(offset) / scale;
  const factor = movingAway ? Math.max(MIN_RESISTANCE, 1 / (1 + ratio * ratio)) : RETURN_ASSIST;
  let next = offset + delta * factor;
  if (hardLimit !== Infinity) next = THREE.MathUtils.clamp(next, -hardLimit, hardLimit);
  return next + rest;
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
    /**
     * Rotation is only meaningful once something has been raised off the
     * ground. With just the overview there is nothing to look around, so the
     * canvas stays a plain 2D pan/zoom surface.
     */
    this.allowRotation = false;

    // pivot mode
    this.pivotOrigin = new THREE.Vector3();
    this.pivotHeading = 0;
    /** Distance to the plane being faced; sets the scale of pivot gestures. */
    this.pivotDistance = 2000;
    /** Half the angle between the two plane headings; the free-look corridor. */
    this.pivotArcHalf = Math.PI;
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

  /**
   * Highest pitch that still keeps the camera above the ground plane.
   *
   * Positive pitch lowers the camera: it sits at
   * `target.y - sin(pitch) * distance`. An earlier version had that sign the
   * wrong way round and so guarded the side the camera was never going to leave
   * from, which is why dragging down went straight under the ground and showed
   * the overview mirrored from below.
   *
   * Solving for the minimum height gives the ceiling, and it tightens
   * automatically as the camera moves closer in.
   */
  _pitchCeiling() {
    if (this.mode !== "canvas") return HARD_PITCH;
    const ratio = (this.target.y - MIN_CAMERA_HEIGHT) / Math.max(this.distance, 1e-6);
    if (ratio >= 1) return HARD_PITCH;
    if (ratio <= -1) return -HARD_PITCH;
    return Math.min(HARD_PITCH, Math.asin(ratio));
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
      this.pivotArcHalf = Math.abs(delta) / 2;
    } else {
      this.pivotCenterYaw = angles[0] ?? 0;
      this.pivotArcHalf = THREE.MathUtils.degToRad(30);
    }

    this.pivotHeading = angles[0] ?? 0;
    this.pitch *= TILT_CARRYOVER;
    if (snap || !this._initialised) this._snap();
  }

  /** Swing the head to face one of the pivot headings. */
  lookAlong(direction) {
    if (this.mode !== "pivot") return;
    this.pivotHeading = Math.atan2(direction.x, direction.z);
  }

  /**
   * Turning the head between the two trees is free; turning away from both is
   * weighted, and turning back is assisted.
   *
   * This used to be a hard clamp at the arc plus a few degrees, which with two
   * planes facing each other meant a wall at about 180 degrees of total sweep -
   * exactly the "cannot rotate freely" the corridor was never meant to cause.
   * Resistance outside the arc gives the same protection without the wall.
   */
  _resistedLook(current, delta) {
    let offset = current - this.pivotCenterYaw;
    while (offset > Math.PI) offset -= Math.PI * 2;
    while (offset < -Math.PI) offset += Math.PI * 2;

    const movingAway = offset === 0 || Math.sign(delta) === Math.sign(offset);
    const excess = Math.max(0, Math.abs(offset) - this.pivotArcHalf);
    const ratio = excess / PIVOT_LOOK_SCALE;
    const factor = movingAway ? Math.max(MIN_RESISTANCE, 1 / (1 + ratio * ratio)) : RETURN_ASSIST;
    return this.pivotCenterYaw + offset + delta * factor;
  }

  /**
   * Distance from the viewer to the plane it is currently facing.
   *
   * Gesture speed has to be calibrated against this, not against the fixed span
   * set when the pair was arranged. Once the viewer walks up close, a strafe
   * scaled by the original span sends the content flying - measured at 33x the
   * drag before this was tracked.
   */
  _facingDistance() {
    if (!this.pivotAxis || !this.pivotCentre) return this.pivotDistance;
    const along = this.pivotOrigin.clone().sub(this.pivotCentre).dot(this.pivotAxis);
    const facingPositive = this._pivotForward().dot(this.pivotAxis) > 0;
    const distance = facingPositive ? this.pivotSpan - along : this.pivotSpan + along;
    return THREE.MathUtils.clamp(distance, this.minDistance, this.maxDistance);
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
    // Zooming in raises the floor, so re-apply it every frame rather than only
    // at the moment of the gesture.
    if (this.mode === "canvas") {
      this.pitch = THREE.MathUtils.clamp(this.pitch, -HARD_PITCH, this._pitchCeiling());
    } else {
      this.pivotOrigin.y = Math.max(MIN_CAMERA_HEIGHT, this.pivotOrigin.y);
    }
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
    // Nothing raised means nothing to look around: ignore the rotate gesture
    // rather than letting it tip the flat overview.
    if (secondary && !this.allowRotation) {
      this._pointer = null;
      return;
    }
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
      this.pivotHeading = this._resistedLook(this.pivotHeading, dx * LOOK_SPEED);
      this.pitch = resistedRotation(this.pitch, dy * LOOK_SPEED, PIVOT_PITCH_SCALE, {
        hardLimit: HARD_PITCH,
      });
      return;
    }

    if (this._mode === "walk") {
      // Same world-units-per-pixel rule as canvas panning, using the distance to
      // the plane being faced, so a drag covers the same amount of screen.
      //
      // The right vector is cross(forward, up). It was previously written as its
      // negative, so strafing carried the viewer the same way as the mouse and
      // the content slid against it - the one gesture that did not follow the
      // pointer.
      const perPixel = this._perPixel(this._facingDistance());
      const right = new THREE.Vector3(
        -Math.cos(this.pivotHeading),
        0,
        Math.sin(this.pivotHeading),
      );
      this.pivotOrigin.addScaledVector(right, -dx * perPixel);
      this.pivotOrigin.y = Math.max(MIN_CAMERA_HEIGHT, this.pivotOrigin.y + dy * perPixel);
      this._clampPivotOrigin();
      return;
    }

    if (this._mode === "tilt") {
      // No yaw limit at all: keep dragging and the view swings behind the tree.
      //
      // Sign note: rotation is judged by which face of the tree comes into
      // view, not by which way the pixels slide. Dragging right swings the
      // camera to the tree's LEFT, so its left side is what you end up looking
      // at - the same thing turning your head does in the two-plane view.
      // Optimising instead for "content follows the pointer" sends the camera
      // the other way and was wrong.
      this.yaw = resistedRotation(this.yaw, -dx * ROTATE_SPEED, YAW_SCALE);
      // Same rule as yaw: rotation is judged by which face comes into view.
      // Dragging down lifts the camera so the top of the tree is what you end
      // up looking at, matching drag-right revealing its left side.
      this.pitch = THREE.MathUtils.clamp(
        resistedRotation(this.pitch, -dy * ROTATE_SPEED, PITCH_SCALE, { hardLimit: HARD_PITCH }),
        -HARD_PITCH,
        this._pitchCeiling(),
      );
      return;
    }

    // Pan along the CAMERA's screen axes, not the plane's fixed basis.
    //
    // `frame.right` is a property of the plane, so once the view swung past 90
    // degrees - or right around behind the tree - it no longer pointed at
    // screen-right and dragging moved the canvas the wrong way. Deriving the
    // direction from the camera and projecting it back onto the plane keeps the
    // content following the mouse from every angle.
    const perPixel = this._perPixel(this.distance);
    const cameraRight = new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld, 0);
    const cameraUp = new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld, 1);
    const move = cameraRight
      .multiplyScalar(-dx * perPixel)
      .addScaledVector(cameraUp, dy * perPixel);
    this.pan.x += move.dot(this.frame.right);
    this.pan.y += move.dot(this.frame.up);
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
      const current = this._facingDistance();
      const next = THREE.MathUtils.clamp(current * factor, this.minDistance, this.maxDistance);
      this.pivotOrigin.addScaledVector(this._pivotForward(), current - next);
      this.pivotOrigin.y = Math.max(MIN_CAMERA_HEIGHT, this.pivotOrigin.y);
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
      // Square up on whichever tree is nearest, not the empty midpoint.
      this.pivotHeading = this._nearestHeading();
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
