// Three.js 场景封装 (§4.4): 视口 + 变换 gizmo + PLY 点云 + 原画幽灵底图
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { TransformControls } from 'three/addons/controls/TransformControls.js'
import { PLYLoader } from 'three/addons/loaders/PLYLoader.js'

/** 初始化视口。返回 controller 对象。 */
export function initScene(container, { onTransformEnd, onSelect }) {
  const renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setPixelRatio(window.devicePixelRatio)
  renderer.setSize(container.clientWidth, container.clientHeight)
  container.appendChild(renderer.domElement)

  const scene = new THREE.Scene()
  scene.background = new THREE.Color(0x0b0d12)

  // 相机锁定为原画内参 (§3.4): 位于原点看向 -Z, fov 50
  const camera = new THREE.PerspectiveCamera(50, container.clientWidth / container.clientHeight, 0.1, 100)
  camera.position.set(0, 0, 8)
  camera.lookAt(0, 0, -1)

  const controls = new OrbitControls(camera, renderer.domElement)
  controls.target.set(0, 0, 0)

  scene.add(new THREE.AmbientLight(0xffffff, 1.2))
  const dir = new THREE.DirectionalLight(0xffffff, 1.0)
  dir.position.set(2, 4, 4)
  scene.add(dir)

  // 地面网格
  const grid = new THREE.GridHelper(20, 20, 0x2d3547, 0x222835)
  grid.rotation.x = Math.PI / 2   // 铺在 XY 平面 (相机看 -Z)
  scene.add(grid)

  // 原画幽灵底图 (§4.4 原画对齐模式)
  let ghostMesh = null

  // 物体容器: nodeId -> {points, group}
  const objects = new Map()
  const objectGroup = new THREE.Group()
  scene.add(objectGroup)

  // gizmo
  const gizmo = new TransformControls(camera, renderer.domElement)
  gizmo.addEventListener('dragging-changed', e => { controls.enabled = !e.value })
  gizmo.addEventListener('objectChange', () => {
    if (gizmo.object) pendingTransform = true
  })
  gizmo.addEventListener('mouseUp', () => {
    if (gizmo.object && pendingTransform) {
      pendingTransform = false
      const o = gizmo.object
      const t = {
        translation: [o.position.x, o.position.y, o.position.z],
        rotation_quat: [o.quaternion.x, o.quaternion.y, o.quaternion.z, o.quaternion.w],
        scale: [o.scale.x, o.scale.y, o.scale.z],
      }
      onTransformEnd && onTransformEnd(o.userData.nodeId, t)
    }
  })
  let pendingTransform = false
  scene.add(gizmo)

  // 点击选中
  const raycaster = new THREE.Raycaster()
  const mouse = new THREE.Vector2()
  let downPos = null
  renderer.domElement.addEventListener('pointerdown', e => { downPos = [e.clientX, e.clientY] })
  renderer.domElement.addEventListener('pointerup', e => {
    if (!downPos || Math.hypot(e.clientX - downPos[0], e.clientY - downPos[1]) > 4) return
    const r = renderer.domElement.getBoundingClientRect()
    mouse.x = ((e.clientX - r.left) / r.width) * 2 - 1
    mouse.y = -((e.clientY - r.top) / r.height) * 2 + 1
    raycaster.setFromCamera(mouse, camera)
    const hits = raycaster.intersectObjects(objectGroup.children, true)
    if (hits.length) {
      let obj = hits[0].object
      while (obj && !obj.userData.nodeId) obj = obj.parent
      if (obj) { select(obj.userData.nodeId); onSelect && onSelect(obj.userData.nodeId) }
    } else {
      select(null)
    }
  })

  const plyLoader = new PLYLoader()

  function select(nodeId) {
    if (!nodeId) { gizmo.detach(); return }
    const rec = objects.get(nodeId)
    if (rec) gizmo.attach(rec.group)
  }

  function applyTransform(group, t) {
    if (!t) return
    group.position.set(...t.translation)
    group.quaternion.set(...(t.rotation_quat || [0, 0, 0, 1]))
    group.scale.set(...(t.scale || [1, 1, 1]))
  }

  // 渲染循环
  let raf = 0
  function loop() {
    raf = requestAnimationFrame(loop)
    controls.update()
    renderer.render(scene, camera)
  }
  loop()

  const onResize = () => {
    const w = container.clientWidth, h = container.clientHeight
    if (!w || !h) return
    renderer.setSize(w, h)
    camera.aspect = w / h
    camera.updateProjectionMatrix()
  }
  const ro = new ResizeObserver(onResize)
  ro.observe(container)

  return {
    /** 清空并按 scene.nodes 重建 */
    clearObjects() {
      for (const [, rec] of objects) {
        objectGroup.remove(rec.group)
        rec.group.traverse(c => { if (c.geometry) c.geometry.dispose() })
      }
      objects.clear()
      gizmo.detach()
    },
    /** 加载一个节点 (PLY 点云, 平面 billboard 布局) */
    addObject(node, plyUrl) {
      const group = new THREE.Group()
      group.userData.nodeId = node.node_id
      applyTransform(group, node.transform)
      objectGroup.add(group)
      objects.set(node.node_id, { group })
      plyLoader.load(plyUrl, geo => {
        // PLY 点云: 用顶点色 + Points; mock surfel 半径小 → 放大点尺寸
        if (!geo.attributes.color) {
          const n = geo.attributes.position.count
          const colors = new Float32Array(n * 3)
          for (let i = 0; i < n; i++) { colors[i*3] = 0.4; colors[i*3+1] = 0.65; colors[i*3+2] = 1.0 }
          geo.setAttribute('color', new THREE.BufferAttribute(colors, 3))
        }
        const mat = new THREE.PointsMaterial({ size: 0.05, vertexColors: true, sizeAttenuation: true })
        const pts = new THREE.Points(geo, mat)
        group.add(pts)
      }, undefined, () => { /* PLY 加载失败静默 */ })
    },
    setGhost(url) {
      if (ghostMesh) { scene.remove(ghostMesh); ghostMesh = null }
      if (!url) return
      new THREE.TextureLoader().load(url, tex => {
        const aspect = tex.image.width / tex.image.height
        const h = 6, w = h * aspect
        ghostMesh = new THREE.Mesh(
          new THREE.PlaneGeometry(w, h),
          new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity: 0.18 }))
        ghostMesh.position.z = -3
        scene.add(ghostMesh)
      })
    },
    setGizmoMode(m) { gizmo.setMode(m) },
    select,
    renderer, scene, camera,
  }
}

export function disposeScene(three) {
  if (!three) return
  three.clearObjects()
  three.renderer.dispose()
  three.renderer.domElement.remove()
}
