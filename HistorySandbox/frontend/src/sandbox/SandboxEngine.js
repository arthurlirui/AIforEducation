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

// Hover tooltips: raycasting on every pointermove is too expensive, so the
// pick is throttled to this interval; the tooltip position itself follows the
// cursor on every move using the cached latest hit.
const HOVER_RAYCAST_INTERVAL_MS = 50
const TOOLTIP_OFFSET = 12

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

// Ancient place-name label colours by terrain type (deep outline keeps them
// readable on bright terrain): rivers blue-ish, mountains parchment, cities
// and forts accent gold, everything else aged ivory.
const LABEL_COLORS = {
  river: '#7fb8e8',
  mountain: '#d8c9a3',
  city: '#f1c40f',
  fort: '#f1c40f',
}

/** Build a CanvasTexture Sprite that renders text with a dark outline. */
export function makeTextSprite(text, { color = '#f0e6c8', fontSize = 42 } = {}) {
  const pad = 12
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d')
  ctx.font = `${fontSize}px "PingFang SC", "Microsoft YaHei", serif`
  canvas.width = Math.ceil(ctx.measureText(text).width) + pad * 2
  canvas.height = fontSize + pad * 2
  // resizing a canvas resets its 2d state — re-apply the font before drawing
  const c2 = canvas.getContext('2d')
  c2.font = ctx.font
  c2.textBaseline = 'middle'
  c2.textAlign = 'center'
  c2.strokeStyle = 'rgba(11,16,32,0.9)'
  c2.lineWidth = 6
  c2.strokeText(text, canvas.width / 2, canvas.height / 2)
  c2.fillStyle = color
  c2.fillText(text, canvas.width / 2, canvas.height / 2)
  const tex = new THREE.CanvasTexture(canvas)
  tex.colorSpace = THREE.SRGBColorSpace
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false })
  const sprite = new THREE.Sprite(mat)
  const s = 0.045 // world units per pixel
  sprite.scale.set(canvas.width * s, canvas.height * s, 1)
  sprite.renderOrder = 10
  return sprite
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
    this._terrainGroup = new THREE.Group() // ancient-Chinese-style scenario terrain
    this._nationGroup = new THREE.Group()  // scenario areas
    this._actorGroup = new THREE.Group()   // chess pieces
    this._fxGroup = new THREE.Group()      // arrows / highlights / markers
    this._labelGroup = new THREE.Group()   // per-scenario ancient place-name labels
    this._landmarkGroup = new THREE.Group()  // world-scale landmark labels
    this.scene.add(this._worldGroup, this._terrainGroup, this._nationGroup,
                   this._actorGroup, this._fxGroup, this._labelGroup, this._landmarkGroup)

    this._actors = new Map()      // actorId -> { mesh, base }
    this._time = 0
    this._step = null
    this._picking = false         // interaction mode: clicks pick actors / ground
    this._onPickActor = null      // callback(actorId | null)
    this._onPickGround = null     // callback(lonLat | null)
    this._selectedId = null
    this._raycaster = new THREE.Raycaster()
    this._ndc = new THREE.Vector2()
    // hover tooltip state (lazily created DOM element + throttled picking)
    this._tooltipEl = null
    this._hoverLabel = null
    this._lastHoverRaycastAt = 0

    this._buildOcean()
    this._buildContinents()
    this._buildStars()

    this._onResizeBound = () => this._onResize()
    window.addEventListener('resize', this._onResizeBound)
    this.renderer.domElement.addEventListener('pointerdown', (e) => this._onPointerDown(e))
    this.renderer.domElement.addEventListener('pointerup', (e) => this._onPointerUp(e))
    // hover tooltips (same bound-handler pattern so dispose() can remove them)
    this._onPointerMoveBound = (e) => this._onPointerMove(e)
    this._onPointerLeaveBound = () => { this._hoverLabel = null; this._hideTooltip() }
    this.renderer.domElement.addEventListener('pointermove', this._onPointerMoveBound)
    this.renderer.domElement.addEventListener('pointerleave', this._onPointerLeaveBound)
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
        if (o.isMesh && o.userData.isBase) {
          o.material.color.set(on ? '#f1c40f' : '#1a2244')
          o.material.emissive?.set(on ? '#f1c40f' : '#000000')
        }
      })
    }
  }

  _onPointerDown(e) {
    this._downAt = { x: e.clientX, y: e.clientY, t: performance.now() }
  }

  /** Convert a pointer event to NDC coordinates on the canvas. */
  _setNdcFromEvent(e) {
    const rect = this.renderer.domElement.getBoundingClientRect()
    this._ndc.set(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1,
    )
  }

  _onPointerUp(e) {
    if (!this._picking || !this._downAt) return
    const moved = Math.hypot(e.clientX - this._downAt.x, e.clientY - this._downAt.y)
    const dt = performance.now() - this._downAt.t
    this._downAt = null
    if (moved > 6 || dt > 600) return   // it was a drag/orbit, not a click

    this._setNdcFromEvent(e)
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

  // -------------------------------------------------------- hover tooltip

  /**
   * Show a DOM tooltip with the actor/marker name under the cursor.
   * The raycast is throttled to HOVER_RAYCAST_INTERVAL_MS; between picks the
   * tooltip keeps following the cursor with the cached latest hit, so pointer
   * movement never feels laggy. While a button is held (camera drag) the
   * tooltip is hidden so orbiting never pops spurious labels.
   */
  _onPointerMove(e) {
    if (e.buttons !== 0) {   // dragging the camera (or a press) — no tooltip
      this._hoverLabel = null
      this._hideTooltip()
      return
    }
    const now = performance.now()
    if (now - this._lastHoverRaycastAt >= HOVER_RAYCAST_INTERVAL_MS) {
      this._lastHoverRaycastAt = now
      this._hoverLabel = this._raycastLabel(e)
    }
    if (this._hoverLabel) this._showTooltipAt(e)
    else this._hideTooltip()
  }

  /** Raycast actors (chess pieces) and markers (battle shards) for a label. */
  _raycastLabel(e) {
    this._setNdcFromEvent(e)
    this._raycaster.setFromCamera(this._ndc, this.camera)

    const meshes = []
    const labelByMesh = new Map()
    for (const entry of this._actors.values()) {
      if (!entry.mesh.userData.label) continue
      entry.mesh.traverse((o) => {
        if (o.isMesh) { meshes.push(o); labelByMesh.set(o, entry.mesh.userData.label) }
      })
    }
    for (const fx of this._fxGroup.children) {
      if (fx.userData.label && fx.geometry?.type === 'OctahedronGeometry') {
        meshes.push(fx)
        labelByMesh.set(fx, fx.userData.label)
      }
    }
    const hits = this._raycaster.intersectObjects(meshes, false)
    return hits.length ? (labelByMesh.get(hits[0].object) || null) : null
  }

  /** Lazily create the tooltip div; inline styles keep the engine self-contained. */
  _ensureTooltip() {
    if (!this._tooltipEl) {
      const el = document.createElement('div')
      // Chinese-aesthetic dark panel: deep navy bg, aged-ivory text
      el.style.cssText = [
        'position:absolute', 'display:none', 'z-index:20',
        'padding:5px 10px', 'border-radius:8px',
        'background:rgba(11,16,32,0.92)', 'color:#f0e6c8',
        'font-size:12px', 'white-space:nowrap',
        'border:1px solid rgba(120,140,200,0.35)',
        'pointer-events:none',
      ].join(';')
      this.container.appendChild(el)
      this._tooltipEl = el
    }
    return this._tooltipEl
  }

  /** Position the tooltip near the cursor, flipping at the canvas edges. */
  _showTooltipAt(e) {
    const el = this._ensureTooltip()
    el.textContent = this._hoverLabel
    el.style.display = 'block'
    const rect = this.container.getBoundingClientRect()
    let x = e.clientX - rect.left + TOOLTIP_OFFSET
    let y = e.clientY - rect.top + TOOLTIP_OFFSET
    if (x + el.offsetWidth > rect.width) {
      x = e.clientX - rect.left - el.offsetWidth - TOOLTIP_OFFSET
    }
    if (y + el.offsetHeight > rect.height) {
      y = e.clientY - rect.top - el.offsetHeight - TOOLTIP_OFFSET
    }
    el.style.left = `${Math.max(0, x)}px`
    el.style.top = `${Math.max(0, y)}px`
  }

  _hideTooltip() {
    if (this._tooltipEl) this._tooltipEl.style.display = 'none'
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
      const sprite = makeTextSprite(lm.name)
      sprite.position.set(p.x, 3, p.z)
      this._landmarkGroup.add(sprite)
    }
    this._landmarks = labelDivs
  }

  // ---------------------------------------------------------- scenario map

  // ------------------------------------------------- ancient-Chinese terrain
  //
  // Seven stylized feature types rendered in the manner of traditional Chinese
  // map painting (山海经/舆图): mountain ridges, river ribbons, walled cities,
  // pass gates, tree clusters, desert shallows and wasteland marshes.

  _buildTerrain(terrainList) {
    this._clearGroup(this._terrainGroup)
    this._terrainLabels = []
    for (const t of terrainList || []) {
      if (!t || !Array.isArray(t.points) || !t.points.length) continue
      switch (t.type) {
        case 'mountain': this._buildMountain(t); break
        case 'river': this._buildRiver(t); break
        case 'city': this._buildCity(t); break
        case 'fort': this._buildFort(t); break
        case 'forest': this._buildForest(t); break
        case 'desert': this._buildFlat(t, '#d9b779', 0.55); break
        case 'wasteland': this._buildFlat(t, '#6b6347', 0.6); break
        default: break
      }
      if (t.label) {
        // polyline features (mountain ridge / river) anchor at the midpoint of
        // the line; point-like features anchor at their single point
        const anchor = (t.type === 'mountain' || t.type === 'river')
          ? t.points[Math.floor(t.points.length / 2)]
          : t.points[0]
        const p = lonLatToWorld(anchor[0], anchor[1])
        const size = t.size || 1
        let y = 1.6
        if (t.type === 'mountain') y = 3.6 * size + 1      // above the snow caps
        else if (t.type === 'city' || t.type === 'fort') y = 2.2 * size
        const sprite = makeTextSprite(t.label, { color: LABEL_COLORS[t.type] || '#f0e6c8' })
        sprite.position.set(p.x, y, p.z)
        sprite.userData.labelType = t.type
        this._labelGroup.add(sprite)
        this._terrainLabels.push({
          text: t.label,
          pos: p,
          type: t.type,
          note: t.note || '',
        })
      }
    }
  }

  /** 山脉：沿折线脊线竖起一排锥形山峰，山体越高越陡。 */
  _buildMountain(t) {
    const size = t.size || 1
    const pts = t.points.map(([lon, lat]) => lonLatToWorld(lon, lat))
    const curve = pts.length > 1
      ? new THREE.CatmullRomCurve3(pts.map((p) => p.clone().setY(0)), false, 'catmullrom', 0.3)
      : null

    const ridge = curve ? curve.getPoints(Math.max(8, pts.length * 6)) : pts
    const rock = new THREE.MeshStandardMaterial({
      color: t.color || '#6f6a5c', roughness: 0.95, metalness: 0.05, flatShading: true,
    })
    const snow = new THREE.MeshStandardMaterial({
      color: '#cfd8dc', roughness: 0.8, flatShading: true,
    })

    // deterministic pseudo-random so a scenario looks identical every load
    let seedv = 1337
    const rnd = () => ((seedv = (seedv * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff)

    for (let i = 0; i < ridge.length; i += 2) {
      const base = ridge[i]
      const h = (2.2 + rnd() * 2.0) * size
      const r = (0.75 + rnd() * 0.55) * size
      const peak = new THREE.Mesh(new THREE.ConeGeometry(r, h, 5), rock)
      peak.position.set(base.x + (rnd() - 0.5) * 0.8, h / 2, base.z + (rnd() - 0.5) * 0.8)
      peak.rotation.y = rnd() * Math.PI
      this._terrainGroup.add(peak)

      // 雪顶 / 远山高光
      if (h > 3.4 * size) {
        const cap = new THREE.Mesh(new THREE.ConeGeometry(r * 0.42, h * 0.3, 5), snow)
        cap.position.copy(peak.position).setY(h * 0.85)
        cap.rotation.y = peak.rotation.y
        this._terrainGroup.add(cap)
      }
    }

    // 山脊线（像古地图上的「山」字形笔触）
    if (ridge.length > 1) {
      const lineGeo = new THREE.BufferGeometry().setFromPoints(
        ridge.map((p) => new THREE.Vector3(p.x, 0.45, p.z)),
      )
      this._terrainGroup.add(new THREE.Line(
        lineGeo,
        new THREE.LineBasicMaterial({ color: t.color || '#8d8878', transparent: true, opacity: 0.8 }),
      ))
    }
  }

  /** 河流：CatmullRom 河道 + 半透明水带，越宽越显。 */
  _buildRiver(t) {
    const pts = t.points.map(([lon, lat]) => lonLatToWorld(lon, lat))
    if (pts.length < 2) return
    const curve = new THREE.CatmullRomCurve3(
      pts.map((p) => p.clone().setY(0.18)), false, 'catmullrom', 0.4,
    )
    const width = 0.9 * (t.size || 1)

    // 水面管带
    const water = new THREE.Mesh(
      new THREE.TubeGeometry(curve, Math.max(40, pts.length * 12), width, 8, false),
      new THREE.MeshStandardMaterial({
        color: t.color || '#3d7fb8',
        emissive: new THREE.Color(t.color || '#3d7fb8').multiplyScalar(0.35),
        roughness: 0.18, metalness: 0.45,
        transparent: true, opacity: 0.82,
      }),
    )
    this._terrainGroup.add(water)

    // 河岸线
    for (const off of [width * 1.15, -width * 1.15]) {
      const bankPts = curve.getPoints(120).map((p, i, arr) => {
        const prev = arr[Math.max(0, i - 1)]
        const next = arr[Math.min(arr.length - 1, i + 1)]
        const dx = next.x - prev.x, dz = next.z - prev.z
        const len = Math.hypot(dx, dz) || 1
        return new THREE.Vector3(p.x - (dz / len) * off, 0.22, p.z + (dx / len) * off)
      })
      this._terrainGroup.add(new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(bankPts),
        new THREE.LineBasicMaterial({
          color: t.color || '#7fb8e8', transparent: true, opacity: 0.5,
        }),
      ))
    }
  }

  /** 城池：方形城墙 + 四角塔楼 + 中心楼阁（古舆图城符号）。 */
  _buildCity(t) {
    const size = 1.0 * (t.size || 1)
    const [lon, lat] = t.points[0]
    const c = lonLatToWorld(lon, lat)
    const group = new THREE.Group()
    group.position.copy(c)

    const wallMat = new THREE.MeshStandardMaterial({
      color: t.color || '#b08a5a', roughness: 0.85, metalness: 0.1, flatShading: true,
    })
    const roofMat = new THREE.MeshStandardMaterial({
      color: '#8e3b32', roughness: 0.7, flatShading: true,
    })
    const towerMat = new THREE.MeshStandardMaterial({
      color: '#c9a070', roughness: 0.8, flatShading: true,
    })

    const half = 1.35 * size
    const wallH = 0.55 * size
    const wallT = 0.22 * size
    // 四面墙
    for (const [dx, dz, w, d] of [
      [0, -half, half * 2, wallT],
      [0, half, half * 2, wallT],
      [-half, 0, wallT, half * 2],
      [half, 0, wallT, half * 2],
    ]) {
      const wall = new THREE.Mesh(new THREE.BoxGeometry(w, wallH, d), wallMat)
      wall.position.set(dx, wallH / 2, dz)
      group.add(wall)
    }
    // 四角塔楼
    for (const [sx, sz] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
      const tower = new THREE.Mesh(
        new THREE.CylinderGeometry(0.26 * size, 0.32 * size, 1.05 * size, 6), towerMat,
      )
      tower.position.set(sx * half, 0.52 * size, sz * half)
      group.add(tower)
      const roof = new THREE.Mesh(
        new THREE.ConeGeometry(0.42 * size, 0.4 * size, 6), roofMat,
      )
      roof.position.set(sx * half, 1.24 * size, sz * half)
      group.add(roof)
    }
    // 中心楼阁（飞檐）
    const hall = new THREE.Mesh(new THREE.BoxGeometry(0.75 * size, 0.6 * size, 0.75 * size), towerMat)
    hall.position.y = 0.3 * size
    group.add(hall)
    const hallRoof = new THREE.Mesh(new THREE.ConeGeometry(0.72 * size, 0.55 * size, 4), roofMat)
    hallRoof.position.y = 0.88 * size
    hallRoof.rotation.y = Math.PI / 4
    group.add(hallRoof)

    this._terrainGroup.add(group)
  }

  /** 要塞：两座敌楼对峙 + 中间关门的「关隘」形制。 */
  _buildFort(t) {
    const size = 1.0 * (t.size || 1)
    const [lon, lat] = t.points[0]
    const c = lonLatToWorld(lon, lat)
    const group = new THREE.Group()
    group.position.copy(c)

    const stoneMat = new THREE.MeshStandardMaterial({
      color: t.color || '#7d7466', roughness: 0.92, metalness: 0.12, flatShading: true,
    })
    const flagMat = new THREE.MeshStandardMaterial({
      color: '#c0392b', roughness: 0.6, side: THREE.DoubleSide,
    })

    // 两座敌楼
    for (const sx of [-1, 1]) {
      const block = new THREE.Mesh(
        new THREE.BoxGeometry(0.5 * size, 1.5 * size, 0.75 * size), stoneMat,
      )
      block.position.set(sx * 0.72 * size, 0.75 * size, 0)
      group.add(block)
      // 垛口
      const merlon = new THREE.Mesh(
        new THREE.BoxGeometry(0.62 * size, 0.16 * size, 0.85 * size), stoneMat,
      )
      merlon.position.set(sx * 0.72 * size, 1.58 * size, 0)
      group.add(merlon)
    }
    // 关门横梁
    const lintel = new THREE.Mesh(
      new THREE.BoxGeometry(1.5 * size, 0.32 * size, 0.4 * size), stoneMat,
    )
    lintel.position.y = 1.35 * size
    group.add(lintel)
    // 门洞地面标示
    const gate = new THREE.Mesh(
      new THREE.BoxGeometry(0.95 * size, 0.06 * size, 0.6 * size),
      new THREE.MeshBasicMaterial({ color: '#3a3630' }),
    )
    gate.position.y = 0.05
    group.add(gate)
    // 旗杆
    const pole = new THREE.Mesh(
      new THREE.CylinderGeometry(0.05 * size, 0.05 * size, 2.3 * size, 5),
      new THREE.MeshStandardMaterial({ color: '#4a443a' }),
    )
    pole.position.set(-0.72 * size, 1.15 * size, 0)
    group.add(pole)
    const flag = new THREE.Mesh(new THREE.PlaneGeometry(0.62 * size, 0.36 * size), flagMat)
    flag.position.set(-0.4 * size, 2.0 * size, 0)
    group.add(flag)

    this._terrainGroup.add(group)
  }

  /** 树林：以中心点为核心随机散布锥形松树。 */
  _buildForest(t) {
    const [lon, lat] = t.points[0]
    const c = lonLatToWorld(lon, lat)
    const radius = (t.radius || 0.6) * SCALE
    const size = t.size || 1

    let seedv = 4242 + Math.round(lon * 100) + Math.round(lat * 100)
    const rnd = () => ((seedv = (seedv * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff)

    const trunkMat = new THREE.MeshStandardMaterial({ color: '#5a4632', roughness: 0.95 })
    const leafMat = new THREE.MeshStandardMaterial({
      color: t.color || '#2f6b3a', roughness: 0.88, flatShading: true,
    })

    const count = Math.max(6, Math.min(26, Math.round(radius * 7)))
    for (let i = 0; i < count; i++) {
      const a = rnd() * Math.PI * 2
      const r = Math.sqrt(rnd()) * radius
      const x = c.x + Math.cos(a) * r
      const z = c.z + Math.sin(a) * r
      const h = (1.0 + rnd() * 0.9) * size

      const trunk = new THREE.Mesh(
        new THREE.CylinderGeometry(0.06, 0.09, h * 0.42, 5), trunkMat,
      )
      trunk.position.set(x, h * 0.21, z)
      this._terrainGroup.add(trunk)

      const crown = new THREE.Mesh(new THREE.ConeGeometry(0.36 * size, h, 6), leafMat)
      crown.position.set(x, h * 0.42 + h * 0.5, z)
      crown.rotation.y = rnd() * Math.PI
      this._terrainGroup.add(crown)
    }
  }

  /** 沙漠 / 荒原：半透明面片。>=3 点成多边形，否则以中心点画圆盘。 */
  _buildFlat(t, defaultColor, opacity) {
    const color = t.color || defaultColor
    const mat = new THREE.MeshStandardMaterial({
      color, roughness: 0.95, metalness: 0.02,
      transparent: true, opacity,
      side: THREE.DoubleSide, depthWrite: false, flatShading: true,
    })

    if (t.points.length >= 3) {
      const pts = t.points.map(([lon, lat]) => lonLatToWorld(lon, lat))
      const shape = new THREE.Shape()
      shape.moveTo(pts[0].x, pts[0].z)
      for (let i = 1; i < pts.length; i++) shape.lineTo(pts[i].x, pts[i].z)
      shape.closePath()
      const geo = new THREE.ShapeGeometry(shape)
      geo.rotateX(Math.PI / 2)
      const mesh = new THREE.Mesh(geo, mat)
      mesh.position.y = 0.12
      this._terrainGroup.add(mesh)
    } else {
      const [lon, lat] = t.points[0]
      const c = lonLatToWorld(lon, lat)
      const r = (t.radius || 0.6) * SCALE * (t.size || 1)
      const disc = new THREE.Mesh(new THREE.CircleGeometry(r, 28), mat)
      disc.rotation.x = -Math.PI / 2
      disc.position.set(c.x, 0.12, c.z)
      this._terrainGroup.add(disc)

      // 荒原上的稀疏枯草/碎石记号
      if (t.type === 'wasteland') {
        let seedv = 777 + Math.round(lon * 100)
        const rnd = () => ((seedv = (seedv * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff)
        const tuftMat = new THREE.MeshStandardMaterial({ color: '#8a8265', roughness: 1 })
        for (let i = 0; i < 10; i++) {
          const a = rnd() * Math.PI * 2
          const rr = Math.sqrt(rnd()) * r
          const tuft = new THREE.Mesh(new THREE.ConeGeometry(0.07, 0.3, 4), tuftMat)
          tuft.position.set(c.x + Math.cos(a) * rr, 0.25, c.z + Math.sin(a) * rr)
          this._terrainGroup.add(tuft)
        }
      } else {
        // 沙漠沙丘波纹
        let seedv = 999 + Math.round(lon * 100)
        const rnd = () => ((seedv = (seedv * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff)
        const duneMat = new THREE.MeshStandardMaterial({
          color: '#efd39b', roughness: 0.9, flatShading: true,
        })
        for (let i = 0; i < 5; i++) {
          const a = rnd() * Math.PI * 2
          const rr = Math.sqrt(rnd()) * r * 0.8
          const dune = new THREE.Mesh(new THREE.SphereGeometry(0.22 + rnd() * 0.2, 7, 5), duneMat)
          dune.scale.y = 0.35
          dune.position.set(c.x + Math.cos(a) * rr, 0.16, c.z + Math.sin(a) * rr)
          this._terrainGroup.add(dune)
        }
      }
    }
  }

  setScenario(event) {
    // clear per-scenario groups
    this._clearGroup(this._terrainGroup)
    this._clearGroup(this._nationGroup)
    this._clearGroup(this._actorGroup)
    this._clearGroup(this._fxGroup)
    this._clearGroup(this._labelGroup)
    this._actors.clear()
    this._terrainLabels = []
    // pieces/markers of the previous scenario are gone; drop the hover state
    this._hoverLabel = null
    this._hideTooltip()
    // world-scale landmark labels only make sense on world maps; on region /
    // country scenarios they would overlap the ancient place-name labels
    this._landmarkGroup.visible = (event.map?.scale === 'world')

    this.event = event
    this.nations = event.nations || []

    // 中国古代舆图风格地形层（山川/河流/城池/要塞/树林/沙漠/荒原）
    this._buildTerrain(event.map?.terrain || [])

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
    // markers were just replaced (and some actors may be gone): a cached
    // hover hit could show a stale name until the next raycast
    this._hoverLabel = null
    this._hideTooltip()

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
        this._disposeObject(entry.mesh)
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
      if (o.isMesh && o.userData.strengthBar) {
        // 推演可能改变兵力，强度条需跟随当前 strength
        const s = Math.max(0.08, Math.min(1, (a.strength || 100) / 300))
        o.scale.x = s
        o.material.color.set(color)
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
    base.userData.isBase = true   // explicit marker for setSelected highlighting
    group.add(base)

    // strength bar
    const bar = new THREE.Mesh(
      new THREE.BoxGeometry(2.2, 0.28, 0.28),
      new THREE.MeshBasicMaterial({ color }),
    )
    bar.position.y = 1.6
    bar.userData.strengthBar = true
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

  /** Release the GPU resources of a removed object (geometry/material/texture). */
  _disposeObject(obj) {
    obj.traverse?.((o) => {
      o.geometry?.dispose?.()
      if (o.material) {
        (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) => {
          m.map?.dispose?.()   // label sprites own a CanvasTexture
          m.dispose()
        })
      }
    })
  }

  _clearGroup(g) {
    for (const child of [...g.children]) {
      g.remove(child)
      this._disposeObject(child)
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

    // ancient place-name labels: fade out with camera distance so far views
    // don't turn into an unreadable pile of text
    for (const group of [this._labelGroup, this._landmarkGroup]) {
      if (!group.visible) continue
      for (const s of group.children) {
        const dist = this.camera.position.distanceTo(s.position)
        s.material.opacity = Math.max(0, Math.min(0.95, 1.6 - dist / 400))
      }
    }

    this.rig.update(dt)
    this.renderer.render(this.scene, this.camera)
    this._raf = requestAnimationFrame(this._tick.bind(this))
  }

  dispose() {
    cancelAnimationFrame(this._raf)
    window.removeEventListener('resize', this._onResizeBound)
    this.renderer.domElement.removeEventListener('pointermove', this._onPointerMoveBound)
    this.renderer.domElement.removeEventListener('pointerleave', this._onPointerLeaveBound)
    this.rig.dispose()
    // free the CanvasTextures owned by label sprites
    this._clearGroup(this._labelGroup)
    this._clearGroup(this._landmarkGroup)
    this._tooltipEl?.remove()
    this._tooltipEl = null
    this.renderer.dispose()
    this.container.removeChild(this.renderer.domElement)
  }
}
