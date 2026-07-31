import * as THREE from "three";

/**
 * A 2D canvas that happens to live in 3D.
 *
 * This is not an orbit camera. At any moment exactly one plane is "the canvas",
 * and the camera is locked to it: dragging pans parallel to that plane, the
 * wheel dollies along its normal, and screen-up always matches the plane's up.
 * Looking straight at the active plane is therefore the resting state, and the
 * view of it is identical to the flat pyvis-style drawing it was laid out as.
 *
 * Rotation is deliberately not free. Tilt is clamped to a shallow cone around
 * the plane normal (right-drag, or shift + left-drag), which is just enough to
 * perceive which cross-plane edges leave the canvas and where they land,
 * without ever letting the user get lost behind or under the graph.
 *
 * Switching the active plane keeps the same controls and lets the camera glide
 * to the new frame, so expanding a process reads as the canvas moving onto that
 * plane rather than as a camera flying around a model.
 */

const MAX_YAW = THREE.MathUtils.degToRad(24);
const MAX_PITCH = THREE.MathUtils.degToRad(18);
const ROTATE_SPEED = 0.0042;
const ZOOM_SPEED = 0.0012;
const DAMPING = 0.14;
/** Fraction of the current tilt kept when the active canvas changes. */
const TILT_CARRYOVER = 0.25;

export default class CanvasControls {
  constructor(camera, domElement) {
    this.camera = camera;
    this.domElement = domElement;

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

  /**
   * Make `frame` the active canvas. `snap` places the camera immediately;
   * otherwise it glides, which is what makes expanding a process read as the
   * canvas moving rather than as a cut.
   */
  setFrame(frame, { distance, pan = new THREE.Vector2(0, 0), snap = false } = {}) {
    this.frame = {
      origin: frame.origin.clone(),
      right: frame.right.clone().normalize(),
      up: frame.up.clone().normalize(),
      normal: frame.normal.clone().normalize(),
    };
    this.pan.copy(pan);
    if (distance != null) this.distance = THREE.MathUtils.clamp(distance, this.minDistance, this.maxDistance);

    // Land on the new canvas essentially straight-on: a canvas is meant to be
    // read flat, and carrying a full tilt across would drop the user onto a
    // skewed plane. A little is kept so cross-plane edges still read as leaving
    // the surface rather than lying on it.
    this.yaw *= TILT_CARRYOVER;
    this.pitch *= TILT_CARRYOVER;

    if (snap || !this._initialised) {
      this._initialised = true;
      const { position, target, up } = this._desired();
      this._smoothedPosition.copy(position);
      this._smoothedTarget.copy(target);
      this._smoothedUp.copy(up);
      this._apply();
    }
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

  _tiltQuaternion() {
    const yaw = new THREE.Quaternion().setFromAxisAngle(this.frame.up, this.yaw);
    const pitchAxis = this.frame.right.clone().applyQuaternion(yaw);
    const pitch = new THREE.Quaternion().setFromAxisAngle(pitchAxis, this.pitch);
    return pitch.multiply(yaw);
  }

  _desired() {
    const tilt = this._tiltQuaternion();
    const direction = this.frame.normal.clone().applyQuaternion(tilt);
    const up = this.frame.up.clone().applyQuaternion(tilt);
    const target = this.target;
    return { position: target.clone().addScaledVector(direction, this.distance), target, up };
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
    this._mode = event.button === 2 || event.button === 1 || event.shiftKey ? "tilt" : "pan";
    this._last.set(event.clientX, event.clientY);
    this.domElement.setPointerCapture?.(event.pointerId);
  }

  _handlePointerMove(event) {
    if (this._pointer !== event.pointerId) return;
    const dx = event.clientX - this._last.x;
    const dy = event.clientY - this._last.y;
    this._last.set(event.clientX, event.clientY);

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
    const factor = Math.exp(event.deltaY * ZOOM_SPEED);
    this.distance = THREE.MathUtils.clamp(
      this.distance * factor,
      this.minDistance,
      this.maxDistance,
    );
  }

  /** Return to looking dead-on at the active canvas. */
  resetTilt() {
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
