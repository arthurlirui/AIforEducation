/**
 * PaintingScene — Three.js parallax layer engine.
 *
 * Loads the backend's rendered RGBA layers (sky/hills/cypress...) as
 * textured planes, places each at its authored `depth` on the z axis,
 * and exposes:
 *   - mouse-driven parallax (camera orbit sway)
 *   - idle breathing animation (subtle per-layer float)
 *   - chapter camera moves: focusLayer(role, {camera, zoom}) with smooth
 *     easing toward the target layer plane
 *   - dispose() for Vue unmount
 */
import * as THREE from 'three'

export class PaintingScene {
  /**
   * @param {HTMLElement} container
   * @param {{layers: Array<{role:string, depth:number, url:string}>, hero_palette?: string[]}} spec
   */
  constructor(container, spec) {
    this.container = container
    this.spec = spec
    this.layers = []              // {mesh, role, depth, baseY}
    this.target = null            // camera focus target
    this.pointer = { x: 0, y: 0 } // normalized -1..1
    this.breathT = 0
    this.disposed = false

    this._initRenderer()
    this._initCamera()
    this._initScene()
    this._bindEvents()
    this._animate()
  }

  _initRenderer() {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    this.renderer.setSize(this.container.clientWidth, this.container.clientHeight)
    this.container.appendChild(this.renderer.domElement)
  }

  _initCamera() {
    this.camera = new THREE.PerspectiveCamera(
      42,
      this.container.clientWidth / this.container.clientHeight,
      0.1,
      200,
    )
    this.cameraHome = new THREE.Vector3(0, 0, 26)
    this.camera.position.copy(this.cameraHome)
  }

  _initScene() {
    this.scene = new THREE.Scene()
    this.scene.fog = new THREE.FogExp2(0x0b0d14, 0.008)
    const ambient = new THREE.AmbientLight(0xffffff, 1.05)
    this.scene.add(ambient)
    const key = new THREE.DirectionalLight(0xfff2d0, 0.55)
    key.position.set(4, 6, 18)
    this.scene.add(key)

    // museum backdrop behind the deepest layer
    const backdrop = new THREE.Mesh(
      new THREE.PlaneGeometry(90, 60),
      new THREE.MeshBasicMaterial({ color: 0x07080e }),
    )
    backdrop.position.z = -34
    this.scene.add(backdrop)

    // painting frame (thin dark box around the layer stack)
    const frameGroup = new THREE.Group()
    const frameMat = new THREE.MeshStandardMaterial({ color: 0x1b1712, roughness: 0.85 })
    const fw = 18.4, fh = 13.9, ft = 0.35
    const bars = [
      [0, fh / 2, fw, ft], [0, -fh / 2, fw, ft],
      [-fw / 2, 0, ft, fh], [fw / 2, 0, ft, fh],
    ]
    for (const [x, y, w, h] of bars) {
      const bar = new THREE.Mesh(new THREE.BoxGeometry(w, h, 1.1), frameMat)
      bar.position.set(x, y, 0.7)
      frameGroup.add(bar)
    }
    frameGroup.position.z = 3.2
    this.scene.add(frameGroup)

    this._loadLayers()
  }

  async _loadLayers() {
    const loader = new THREE.TextureLoader()
    loader.setCrossOrigin('anonymous')
    // base painting plane size (4:3)
    const W = 17.5, H = 13.1
    const loads = this.spec.layers.map(
      (l) =>
        new Promise((resolve) => {
          loader.load(l.url, (tex) => resolve({ l, tex }), undefined, () => resolve({ l, tex: null }))
        }),
    )
    const results = await Promise.all(loads)
    // 页面已切走（dispose 已执行）则直接丢弃，避免向 scene 追加泄漏的网格
    if (this.disposed) {
      for (const { tex } of results) if (tex) tex.dispose()
      return
    }
    for (const { l, tex } of results) {
      const mat = tex
        ? new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false })
        : new THREE.MeshBasicMaterial({ color: 0x222222, transparent: true, opacity: 0.3 })
      if (tex) {
        // three r152+ 不再自动标记贴图色彩空间，缺省会偏灰发白
        tex.colorSpace = THREE.SRGBColorSpace
      }
      const mesh = new THREE.Mesh(new THREE.PlaneGeometry(W, H), mat)
      // z position: positive depth (foreground) toward camera
      mesh.position.z = l.depth * 0.42
      mesh.renderOrder = 100 + l.depth
      this.scene.add(mesh)
      this.layers.push({ mesh, role: l.role, depth: l.depth, baseY: 0 })
    }
  }

  _bindEvents() {
    this._onPointer = (e) => {
      const r = this.container.getBoundingClientRect()
      this.pointer.x = ((e.clientX - r.left) / r.width) * 2 - 1
      this.pointer.y = ((e.clientY - r.top) / r.height) * 2 - 1
    }
    this.container.addEventListener('pointermove', this._onPointer)

    this._onResize = () => {
      if (this.disposed) return
      const w = this.container.clientWidth, h = this.container.clientHeight
      this.camera.aspect = w / h
      this.camera.updateProjectionMatrix()
      this.renderer.setSize(w, h)
    }
    window.addEventListener('resize', this._onResize)
  }

  /** Focus a chapter camera move. focus = {layer, camera, zoom} */
  focusLayer(focus) {
    if (!focus) { this.target = null; return }
    const layer = this.layers.find((l) => l.role === focus.layer)
    const zoom = focus.zoom || 1.0
    if (!layer) {
      // pull-back / overview without a specific layer
      this.target = focus.camera === 'pull-back'
        ? { pos: new THREE.Vector3(0, 0, this.cameraHome.z + 9), look: new THREE.Vector3(0, 0, 0), k: 0.06 }
        : null
      return
    }
    const z = layer.mesh.position.z
    let camPos, k = 0.05
    switch (focus.camera) {
      case 'extreme-close-up':
        camPos = new THREE.Vector3(layer.role === 'pearl' ? 3.2 : 0, 0.5, z + 5.5 / zoom)
        k = 0.045
        break
      case 'close-up':
        camPos = new THREE.Vector3(0, 0, z + 8.5 / zoom)
        break
      case 'medium':
        camPos = new THREE.Vector3(0, 0, z + 12.5 / zoom)
        break
      case 'pull-back':
        camPos = new THREE.Vector3(0, 0, this.cameraHome.z + 9)
        break
      default: // overview
        camPos = new THREE.Vector3(0, 0, this.cameraHome.z)
    }
    this.target = { pos: camPos, look: layer.mesh.position.clone(), k }
  }

  _animate = () => {
    if (this.disposed) return
    this._raf = requestAnimationFrame(this._animate)
    this.breathT += 0.016

    // idle breathing: each layer floats slightly out of phase
    for (let i = 0; i < this.layers.length; i++) {
      const l = this.layers[i]
      l.mesh.position.y = l.baseY + Math.sin(this.breathT * 0.7 + i * 1.3) * 0.05
      l.mesh.rotation.z = Math.sin(this.breathT * 0.4 + i) * 0.004
    }

    // camera: blend chapter target + pointer parallax
    const px = this.pointer.x, py = this.pointer.y
    const base = this.target ? this.target.pos : this.cameraHome
    const look = this.target ? this.target.look : new THREE.Vector3(0, 0, 0)
    const k = this.target ? this.target.k : 0.05
    const desired = new THREE.Vector3(
      base.x + px * 1.9,
      base.y - py * 1.2,
      base.z,
    )
    this.camera.position.lerp(desired, k)
    const lookCur = this.camera.userData.look || look.clone()
    lookCur.lerp(look, k)
    this.camera.userData.look = lookCur
    this.camera.lookAt(lookCur)

    this.renderer.render(this.scene, this.camera)
  }

  dispose() {
    this.disposed = true
    cancelAnimationFrame(this._raf)
    this.container.removeEventListener('pointermove', this._onPointer)
    window.removeEventListener('resize', this._onResize)
    for (const l of this.layers) {
      l.mesh.geometry.dispose()
      if (l.mesh.material.map) l.mesh.material.map.dispose()
      l.mesh.material.dispose()
    }
    this.renderer.dispose()
    if (this.renderer.domElement.parentNode === this.container) {
      this.container.removeChild(this.renderer.domElement)
    }
  }
}
