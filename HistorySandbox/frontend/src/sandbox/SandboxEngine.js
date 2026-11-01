// HistorySandbox — Three.js stylized 3D sandbox engine.
//
// The map lives on the XZ plane. lon/lat are mapped to engine units:
//   x = (lon - 10) * SCALE, z = -(lat - 30) * SCALE
// Continents are extruded low-poly plates with glowing rims; scenario
// nations are raised translucent plates; actors are stylized chess pieces;
// arrows are animated flowing tubes; highlights pulse on the surface.
import * as THREE from 'three'
import { CameraRig } from './cameraRig.js'
import { CONTINENTS, LANDMARKS } from './worldGeo.js'

const SCALE = 1.4
const LON0 = 10, LAT0 = 30

export function lonLatToWorld(lon, lat) {
  return new THREE.Vector3((lon - LON0) * SCALE, 0, -(lat - LAT0) * SCALE)
}

function nationColor(nations, id, fallback = '#7f8c9b') {
  const n = (nations || []).find((x) => x.id === id)
  return n ? n.color : fallback
}

const ACTOR_KINDS = {
  army: { shape: 'cone', color: '#ffffff' },
  fleet: { shape: 'boat', color: '#ffffff' },
  person: { shape: 'pawn', color: '#ffffff' },
  trade: { shape: 'box', color: '#ffffff' },
  city: { shape: 'cylinder', color: '#ffffff' },
  battle: { shape: 'octa', color: '#ffffff' },
}

export class SandboxEngine {
  constructor(container) {
    this.container = container

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    this.renderer.setSize(container.clientWidth, container.clientHeight)
    container.appendChild(this.renderer.domElement)

    this.scene = new THREE.Scene()
    this.scene.background = new THREE.Color('#0b1020')
    this.scene.fog = new THREE.Fog('#0b1020', 220, 520)

    this.camera = new THREE.PerspectiveCamera(
      50, container.clientWidth / container.clientHeight, 0.1, 2000,
    )
    this.rig = new CameraRig(this.camera, this.renderer.domElement)
    this.rig.distance = 170

    // lights
    this.scene.add(new THREE.AmbientLight('#8899cc', 0.7))
    const dir = new THREE.DirectionalLight('#fff4dd', 1.4)
    dir.position.set(60, 120, 80)
    this.scene.add(dir)
    const rim = new THREE.DirectionalLight('#4466ff', 0.5)
    rim.position.set(-80, 40, -60)
    this.scene.add(rim)

    // groups
    this._worldGroup = new THREE.Group()   // static terrain
    this._nationGroup = new THREE.Group()  // scenario areas
    this._actorGroup = new THREE.Group()   // chess pieces
    this._fxGroup = new THREE.Group()      // arrows / highlights / markers
    this.scene.add(this._worldGroup, this._nationGroup, this._actorGroup, this._fxGroup)

    this._actors = new Map()      // actorId -> { mesh, base }
    this._time = 0
    this._step = null
    this._picking = false         // interaction mode: clicks pick actors / ground
    this._onPickActor = null      // callback(actorId | null)
    this._onPickGround = null     // callback(lonLat | null)
    this._selectedId = null
    this._raycaster = new THREE.Raycaster()
    this._ndc = new THREE.Vector2()

    this._buildOcean()
    this._buildContinents()
    this._buildStars()

    window.addEventListener('resize', () => this._onResize())
    this.renderer.domElement.addEventListener('pointerdown', (e) => this._onPointerDown(e))
    this.renderer.domElement.addEventListener('pointerup', (e) => this._onPointerUp(e))
    this._clock = new THREE.Clock()
    this._raf = requestAnimationFrame(this._tick.bind(this))
  }

  // ------------------------------------------------------------ interaction

  setPicking(enabled, { onPickActor, onPickGround } = {}) {
    this._picking = enabled
    this._onPickActor = onPickActor || null
    this._onPickGround = onPickGround || null
    this.renderer.domElement.style.cursor = enabled ? 'crosshair' : 'default'
  }

  setSelected(actorId) {
    this._selectedId = actorId
    for (const [id, entry] of this._actors) {
      const on = id === actorId
      entry.mesh.traverse((o) => {
        if (o.isMesh && o.geometry?.type === 'CylinderGeometry' && o.position.y < 0) {
          o.material.color.set(on ? '#f1c40f' : '#1a2244')
          o.material.emissive?.set(on ? '#f1c40f' : '#000000')
        }
      })
    }
  }

  _onPointerDown(e) {
    this._downAt = { x: e.clientX, y: e.clientY, t: performance.now() }
  }

  _onPointerUp(e) {
    if (!this._picking || !this._downAt) return
    const moved = Math.hypot(e.clientX - this._downAt.x, e.clientY - this._downAt.y)
    const dt = performance.now() - this._downAt.t
    this._downAt = null
    if (moved > 6 || dt > 600) return   // it was a drag/orbit, not a click

    const rect = this.renderer.domElement.getBoundingClientRect()
    this._ndc.set(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1,
    )
    this._raycaster.setFromCamera(this._ndc, this.camera)

    // 1) try actor meshes first
    const meshes = []
    const idByMesh = new Map()
    for (const [id, entry] of this._actors) {
      entry.mesh.traverse((o) => { if (o.isMesh) { meshes.push(o); idByMesh.set(o, id) } })
    }
    const hits = this._raycaster.intersectObjects(meshes, false)
    if (hits.length) {
      this._onPickActor?.(idByMesh.get(hits[0].object))
      return
    }

    // 2) fall back to the ocean plane (y=0 world → lon/lat)
    const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0)
    const pt = new THREE.Vector3()
    if (this._raycaster.ray.intersectPlane(plane, pt)) {
      const lon = pt.x / SCALE + LON0
      const lat = -pt.z / SCALE + LAT0
      if (lon >= -180 && lon <= 180 && lat >= -85 && lat <= 85) {
        this._onPickGround?.([lon, lat])
        return
      }
    }
    this._onPickActor?.(null)
  }

  // ------------------------------------------------------------ world base

  _buildOcean() {
    const geo = new THREE.CircleGeometry(600, 96)
    const mat = new THREE.MeshStandardMaterial({
      color: '#0e1a3a', roughness: 0.35, metalness: 0.55,
      transparent: true, opacity: 0.96,
    })
    const mesh = new THREE.Mesh(geo, mat)
    mesh.rotation.x = -Math.PI / 2
    mesh.position.y = -0.6
    this._worldGroup.add(mesh)

    // grid lines
    const grid = new THREE.GridHelper(600, 48, '#1c2a55', '#141f42')
    grid.position.y = -0.55
    this._worldGroup.add(grid)
  }

  _buildStars() {
    const geo = new THREE.BufferGeometry()
    const n = 700, pos = new Float32Array(n * 3)
    for (let i = 0; i < n; i++) {
      const r = 300 + Math.random() * 500
      const t = Math.random() * Math.PI * 2
      const p = Math.acos(2 * Math.random() - 1)
      pos[i * 3] = r * Math.sin(p) * Math.cos(t)
      pos[i * 3 + 1] = Math.abs(r * Math.cos(p)) * 0.6 + 40
      pos[i * 3 + 2] = r * Math.sin(p) * Math.sin(t)
    }
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3))
    this._worldGroup.add(new THREE.Points(
      geo, new THREE.PointsMaterial({ color: '#8fa8ff', size: 1.2, sizeAttenuation: true }),
    ))
  }

  _buildContinents() {
    for (const c of CONTINENTS) {
      const shape = new THREE.Shape()
      const pts = c.points.map(([lon, lat]) => lonLatToWorld(lon, lat))
      shape.moveTo(pts[0].x, pts[0].z)
      for (let i = 1; i < pts.length; i++) shape.lineTo(pts[i].x, pts[i].z)
      shape.closePath()

      const height = 1.6
      const geo = new THREE.ExtrudeGeometry(shape, { depth: height, bevelEnabled: false })
      geo.rotateX(Math.PI / 2)
      const mat = new THREE.MeshStandardMaterial({
        color: c.color, roughness: 0.85, metalness: 0.05, flatShading: true,
      })
      const mesh = new THREE.Mesh(geo, mat)
      mesh.position.y = -height + 0.4
      this._worldGroup.add(mesh)

      // glowing rim
      const lineGeo = new THREE.BufferGeometry().setFromPoints(
        pts.map((p) => new THREE.Vector3(p.x, 0.5, p.z)),
      )
      const line = new THREE.Line(
        lineGeo,
        new THREE.LineBasicMaterial({ color: '#7fd8ff', transparent: true, opacity: 0.5 }),
      )
      this._worldGroup.add(line)
    }

    // landmark dots + labels
    const labelDivs = []
    for (const lm of LANDMARKS) {
      const p = lonLatToWorld(lm.lon, lm.lat)
      const dot = new THREE.Mesh(
        new THREE.SphereGeometry(0.35, 8, 8),
        new THREE.MeshBasicMaterial({ color: '#f1c40f' }),
      )
      dot.position.set(p.x, 0.8, p.z)
      this._worldGroup.add(dot)
      labelDivs.push({ text: lm.name, pos: p })
    }
    this._landmarks = labelDivs
  }

  // ---------------------------------------------------------- scenario map

  setScenario(event) {
    // clear per-scenario groups
    this._clearGroup(this._nationGroup)
    this._clearGroup(this._actorGroup)
    this._clearGroup(this._fxGroup)
    this._actors.clear()

    this.event = event
    this.nations = event.nations || []

    // nation plates
    for (const area of event.map?.areas || []) {
      const color = nationColor(this.nations, area.nation)
      const pts = area.points.map(([lon, lat]) => lonLatToWorld(lon, lat))
      if (pts.length < 3) continue
      const shape = new THREE.Shape()
      shape.moveTo(pts[0].x, pts[0].z)
      for (let i = 1; i < pts.length; i++) shape.lineTo(pts[i].x, pts[i].z)
      shape.closePath()
      const geo = new THREE.ExtrudeGeometry(shape, { depth: 2.6, bevelEnabled: false })
      geo.rotateX(Math.PI / 2)
      const mat = new THREE.MeshStandardMaterial({
        color, roughness: 0.6, metalness: 0.1,
        transparent: true, opacity: 0.45, flatShading: true,
        emissive: new THREE.Color(color).multiplyScalar(0.25),
      })
      const mesh = new THREE.Mesh(geo, mat)
      mesh.position.y = -2.6 + 0.6
      this._nationGroup.add(mesh)

      const lineGeo = new THREE.BufferGeometry().setFromPoints(
        pts.map((p) => new THREE.Vector3(p.x, 0.75, p.z)),
      )
      this._nationGroup.add(new THREE.Line(
        lineGeo,
        new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.95 }),
      ))
    }

    // initial camera framing on the map center
    const [clon, clat] = event.map?.center || [20, 30]
    const zoom = event.map?.zoom || 3
    const center = lonLatToWorld(clon, clat)
    this.rig.target.copy(center)
    this.rig.distance = 400 / zoom
    this.rig.flyTo(center, 340 / zoom, 100)
  }

  // --------------------------------------------------------------- a step

  applyStep(step, { animateCamera = true } = {}) {
    this._step = step
    this._clearGroup(this._fxGroup)

    // --- actors: create/update/remove with position tween
    const seen = new Set()
    for (const a of step.actors || []) {
      seen.add(a.id)
      const target = lonLatToWorld(a.position[0], a.position[1])
      let entry = this._actors.get(a.id)
      if (!entry) {
        const mesh = this._makeActorMesh(a)
        mesh.position.copy(target).setY(0.9)
        this._actorGroup.add(mesh)
        entry = { mesh, from: target.clone(), to: target.clone(), t0: this._time, nation: a.nation }
        // spawn pop-in
        mesh.scale.setScalar(0.01)
        entry.spawn = this._time
        this._actors.set(a.id, entry)
      } else {
        entry.from = entry.mesh.position.clone().setY(0.9)
        entry.to = target
        entry.t0 = this._time
        entry.spawn = null
        this._updateActorLook(entry, a)
      }
    }
    for (const [id, entry] of this._actors) {
      if (!seen.has(id)) {
        this._actorGroup.remove(entry.mesh)
        this._actors.delete(id)
      }
    }

    // --- arrows
    for (const arr of step.arrows || []) {
      this._fxGroup.add(this._makeArrow(arr))
    }

    // --- highlights (pulsing rings)
    this._highlights = []
    for (const h of step.highlights || []) {
      const p = lonLatToWorld(h.position[0], h.position[1])
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(h.radius * SCALE * 0.55, h.radius * SCALE * 0.75, 48),
        new THREE.MeshBasicMaterial({
          color: h.color, transparent: true, opacity: 0.85,
          side: THREE.DoubleSide, depthWrite: false,
        }),
      )
      ring.rotation.x = -Math.PI / 2
      ring.position.set(p.x, 0.65, p.z)
      this._fxGroup.add(ring)
      this._highlights.push(ring)
    }

    // --- markers (battle/treaty icons as small crystal shards)
    for (const m of step.markers || []) {
      const p = lonLatToWorld(m.position[0], m.position[1])
      const mesh = new THREE.Mesh(
        new THREE.OctahedronGeometry(1.1),
        new THREE.MeshStandardMaterial({
          color: m.color, emissive: m.color, emissiveIntensity: 0.7,
          metalness: 0.3, roughness: 0.3,
        }),
      )
      mesh.position.set(p.x, 2.2, p.z)
      mesh.userData.label = m.label
      this._fxGroup.add(mesh)
    }

    // --- camera fly
    if (animateCamera && step.camera) {
      const focus = lonLatToWorld(step.camera[0], step.camera[1])
      const dist = 300 / (step.camera_zoom || 8)
      this.rig.flyTo(focus, dist, 1800)
    }
  }

  _updateActorLook(entry, a) {
    const color = nationColor(this.nations, a.nation)
    entry.mesh.traverse((o) => {
      if (o.isMesh && o.userData.paintable) {
        o.material.color.set(color)
        o.material.emissive.set(color).multiplyScalar(0.35)
      }
    })
    entry.mesh.userData.label = `${a.name}`
  }

  _makeActorMesh(a) {
    const color = nationColor(this.nations, a.nation)
    const kind = ACTOR_KINDS[a.kind] || ACTOR_KINDS.army
    const group = new THREE.Group()
    const mat = new THREE.MeshStandardMaterial({
      color, emissive: new THREE.Color(color).multiplyScalar(0.35),
      metalness: 0.35, roughness: 0.4, flatShading: true,
    })
    mat.userData.paintable = true

    let geo
    switch (kind.shape) {
      case 'boat': geo = new THREE.ConeGeometry(1.1, 1.4, 4); break
      case 'pawn': geo = new THREE.CylinderGeometry(0.45, 0.85, 2.0, 8); break
      case 'box': geo = new THREE.BoxGeometry(1.3, 0.9, 1.3); break
      case 'cylinder': geo = new THREE.CylinderGeometry(1.0, 1.2, 1.4, 12); break
      case 'octa': geo = new THREE.OctahedronGeometry(1.2); break
      default: geo = new THREE.ConeGeometry(1.0, 2.2, 8)  // army tent
    }
    const body = new THREE.Mesh(geo, mat)
    body.userData.paintable = true
    group.add(body)

    // base disc
    const base = new THREE.Mesh(
      new THREE.CylinderGeometry(1.35, 1.5, 0.28, 20),
      new THREE.MeshStandardMaterial({
        color: '#1a2244', metalness: 0.5, roughness: 0.5,
      }),
    )
    base.position.y = -1.1
    group.add(base)

    // strength bar
    const bar = new THREE.Mesh(
      new THREE.BoxGeometry(2.2, 0.28, 0.28),
      new THREE.MeshBasicMaterial({ color }),
    )
    bar.position.y = 1.6
    const s = Math.max(0.08, Math.min(1, (a.strength || 100) / 300))
    bar.scale.x = s
    group.add(bar)

    group.userData.label = a.name
    return group
  }

  _makeArrow(arr) {
    const pts = (arr.points || []).map(([lon, lat]) => lonLatToWorld(lon, lat))
    if (pts.length < 2) return new THREE.Group()
    const curve = new THREE.CatmullRomCurve3(pts.map((p) => p.clone().setY(1.2)), false, 'catmullrom', 0.35)
    const tube = new THREE.Mesh(
      new THREE.TubeGeometry(curve, 90, 0.28 * (arr.width || 1), 8, false),
      new THREE.MeshBasicMaterial({ color: arr.color, transparent: true, opacity: 0.9 }),
    )
    const group = new THREE.Group()
    group.add(tube)

    // arrowhead
    const end = curve.getPoint(1)
    const tangent = curve.getTangent(1)
    const head = new THREE.Mesh(
      new THREE.ConeGeometry(0.75 * (arr.width || 1), 1.8, 10),
      new THREE.MeshBasicMaterial({ color: arr.color }),
    )
    head.position.copy(end)
    head.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), tangent.clone().normalize())
    group.add(head)

    // flowing dashes for dashed arrows
    if (arr.dashed) {
      const dashCount = 14
      for (let i = 0; i < dashCount; i++) {
        const t = i / dashCount
        const d = new THREE.Mesh(
          new THREE.SphereGeometry(0.34, 6, 6),
          new THREE.MeshBasicMaterial({ color: arr.color }),
        )
        d.position.copy(curve.getPoint(t)).y += 0.3
        d.userData.flow = { curve, offset: t }
        group.add(d)
      }
    }
    group.userData.arrowCurve = curve
    group.userData.arrowColor = arr.color
    if (arr.label) group.userData.label = arr.label
    return group
  }

  // ---------------------------------------------------------------- render

  _clearGroup(g) {
    for (const child of [...g.children]) {
      g.remove(child)
      child.traverse?.((o) => {
        o.geometry?.dispose?.()
        if (o.material) {
          (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => m.dispose())
        }
      })
    }
  }

  _onResize() {
    const w = this.container.clientWidth, h = this.container.clientHeight
    this.renderer.setSize(w, h)
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
  }

  _tick() {
    const dt = Math.min(this._clock.getDelta(), 0.1)
    this._time += dt
    const t = this._time

    // actor tweens
    for (const entry of this._actors.values()) {
      const dur = 1.4
      const k = Math.min(1, (t - entry.t0) / dur)
      const s = k * k * (3 - 2 * k)
      entry.mesh.position.lerpVectors(entry.from, entry.to, s)
      entry.mesh.position.y = 0.9 + Math.sin(s * Math.PI) * 2.2 // hop arc
      if (entry.spawn != null) {
        const sk = Math.min(1, (t - entry.spawn) / 0.4)
        entry.mesh.scale.setScalar(sk)
      }
      entry.mesh.rotation.y = t * 0.4
    }

    // highlight pulse
    if (this._highlights) {
      for (let i = 0; i < this._highlights.length; i++) {
        const m = this._highlights[i]
        m.material.opacity = 0.45 + 0.45 * Math.abs(Math.sin(t * 2.2 + i))
        m.scale.setScalar(1 + 0.12 * Math.sin(t * 2.2 + i))
      }
    }

    // marker bobbing
    for (const fx of this._fxGroup.children) {
      if (fx.userData.label && fx.geometry?.type === 'OctahedronGeometry') {
        fx.position.y = 2.2 + Math.sin(t * 2.5) * 0.35
        fx.rotation.y = t * 1.2
      }
      // dashed flow dots
      fx.children?.forEach((c) => {
        if (c.userData.flow) {
          const { curve, offset } = c.userData.flow
          const nt = (offset + t * 0.12) % 1
          c.position.copy(curve.getPoint(nt)).y += 0.3
        }
      })
    }

    this.rig.update(dt)
    this.renderer.render(this.scene, this.camera)
    this._raf = requestAnimationFrame(this._tick.bind(this))
  }

  dispose() {
    cancelAnimationFrame(this._raf)
    this.renderer.dispose()
    this.container.removeChild(this.renderer.domElement)
  }
}
