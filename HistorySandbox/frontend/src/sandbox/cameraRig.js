// Smooth cinematic camera: orbit controls + tweened fly-to moves.
import * as THREE from 'three'

export class CameraRig {
  constructor(camera, dom) {
    this.camera = camera
    this.dom = dom

    this.target = new THREE.Vector3(0, 0, 0)
    this.distance = 100
    this.minDistance = 14
    this.maxDistance = 260

    this.theta = Math.PI * 0.25   // azimuth
    this.phi = Math.PI * 0.32     // polar from Y axis

    this._anim = null

    this._drag = null
    dom.addEventListener('pointerdown', (e) => this._onDown(e))
    window.addEventListener('pointermove', (e) => this._onMove(e))
    window.addEventListener('pointerup', () => this._onUp())
    dom.addEventListener('wheel', (e) => this._onWheel(e), { passive: false })
    // gentle idle auto-rotation
    this.autoRotate = false
  }

  _onDown(e) {
    this._drag = { x: e.clientX, y: e.clientY, theta: this.theta, phi: this.phi }
  }

  _onMove(e) {
    if (!this._drag) return
    const dx = e.clientX - this._drag.x
    const dy = e.clientY - this._drag.y
    this.theta = this._drag.theta - dx * 0.005
    this.phi = Math.max(0.12, Math.min(1.35, this._drag.phi - dy * 0.004))
  }

  _onUp() {
    this._drag = null
  }

  _onWheel(e) {
    e.preventDefault()
    const factor = e.deltaY > 0 ? 1.1 : 0.9
    this.distance = Math.max(this.minDistance, Math.min(this.maxDistance, this.distance * factor))
  }

  /** Tween to look at a point (in engine world units) at a given distance. */
  flyTo(worldPos, distance = null, durationMs = 1600) {
    this._anim = {
      fromTarget: this.target.clone(),
      toTarget: worldPos.clone(),
      fromDist: this.distance,
      toDist: distance != null ? Math.max(this.minDistance, distance) : this.distance,
      fromTheta: this.theta,
      toTheta: this.theta,
      start: performance.now(),
      duration: durationMs,
    }
  }

  update(dt) {
    if (this.autoRotate && !this._drag && !this._anim) {
      this.theta += dt * 0.03
    }
    if (this._anim) {
      const a = this._anim
      let t = (performance.now() - a.start) / a.duration
      if (t >= 1) {
        this.target.copy(a.toTarget)
        this.distance = a.toDist
        this.theta = a.toTheta
        this._anim = null
      } else {
        const s = t * t * (3 - 2 * t) // smoothstep
        this.target.lerpVectors(a.fromTarget, a.toTarget, s)
        this.distance = a.fromDist + (a.toDist - a.fromDist) * s
        this.theta = a.fromTheta + (a.toTheta - a.fromTheta) * s
      }
    }

    const sp = Math.sin(this.phi), cp = Math.cos(this.phi)
    this.camera.position.set(
      this.target.x + this.distance * sp * Math.sin(this.theta),
      this.target.y + this.distance * cp,
      this.target.z + this.distance * sp * Math.cos(this.theta),
    )
    this.camera.lookAt(this.target)
  }
}
