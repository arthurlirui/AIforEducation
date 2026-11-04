<script setup>
// 场景组装编辑器 (§4.4): Three.js 视口 + 变换 gizmo + 大纲树 + 快照
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { api, waitTask } from '../api.js'
import { initScene, disposeScene } from '../three.js'

const props = defineProps({ project: Object })
const emit = defineEmits(['notify', 'notify-error', 'refresh'])

const scene = ref({ nodes: [], camera: {} })
const selectedId = ref(null)
const gizmoMode = ref('translate')   // translate | rotate | scale
const showGhost = ref(true)
const snapshotting = ref(false)

const viewport = ref(null)
let three = null

async function loadScene() {
  try {
    scene.value = await api.getScene(props.project.project_id)
    if (!selectedId.value && scene.value.nodes.length) selectedId.value = scene.value.nodes[0].node_id
    rebuild()
  } catch (e) { emit('notify-error', e) }
}

function rebuild() {
  if (!three) return
  const pid = props.project.project_id
  three.clearObjects()
  for (const n of scene.value.nodes) {
    if (n.kind !== 'gs_object' || !n.visible) continue
    three.addObject(n, api.plyUrl(pid, Number(n.node_id.split('-')[1])))
  }
  three.setGhost(showGhost.value ? api.paintingUrl(pid) : null)
}

// Three.js → PATCH /scene (拖拽结束提交, §3.4 写入协议)
function onTransformEnd(nodeId, transform) {
  const node = scene.value.nodes.find(n => n.node_id === nodeId)
  if (!node) return
  node.transform = transform
  api.patchScene(props.project.project_id, [{ node_id: nodeId, transform }])
    .then(() => emit('notify', `scene.json 已更新: ${nodeId}`, 'ok'))
    .catch(e => emit('notify-error', e))
}

async function toggleVisible(n) {
  try {
    await api.patchScene(props.project.project_id, [{ node_id: n.node_id, visible: !n.visible }])
    n.visible = !n.visible
    rebuild()
  } catch (e) { emit('notify-error', e) }
}

async function snapshot() {
  snapshotting.value = true
  try {
    const { task_id } = await api.snapshot(props.project.project_id)
    const t = await waitTask(task_id)
    if (t.status === 'done') {
      emit('notify', `快照 ${t.result.keyframe_id} 已生成 (${t.result.moved} 个物体已移动)`, 'ok')
      emit('refresh')
    } else emit('notify', `快照失败: ${t.error}`, 'err')
  } catch (e) { emit('notify-error', e) }
  finally { snapshotting.value = false }
}

watch(gizmoMode, m => three && three.setGizmoMode(m))
watch(selectedId, id => three && three.select(id))

onMounted(async () => {
  three = initScene(viewport.value, {
    onTransformEnd,
    onSelect: id => { selectedId.value = id },
  })
  await loadScene()
})
onBeforeUnmount(() => { disposeScene(three); three = null })
</script>

<template>
  <div style="flex:1;display:flex;min-width:0">
    <!-- 大纲树 -->
    <aside style="width:220px;background:var(--panel);border-right:1px solid var(--bd);padding:10px;display:flex;flex-direction:column;gap:4px;flex:none;overflow:auto">
      <b style="font-weight:600;margin-bottom:2px">大纲树</b>
      <div v-for="n in scene.nodes" :key="n.node_id"
           :style="{ display:'flex', alignItems:'center', gap:'6px', padding:'7px 8px', borderRadius:'7px', width:'100%', textAlign:'left',
             color: selectedId===n.node_id ? 'var(--tx)' : 'var(--dim)',
             background: selectedId===n.node_id ? 'var(--panel2)' : 'transparent' }"
           @click="selectedId = n.node_id">
        <button class="mini" @click.stop="toggleVisible(n)" :style="{color: n.visible ? 'var(--cy)' : 'var(--dim)'}">◉</button>
        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ n.label || n.node_id }}</span>
        <span v-if="Object.keys(n.keyframes).length" class="badge warn" style="margin-left:auto;font-size:9px">KF</span>
      </div>
      <div v-if="!scene.nodes.length" class="mini" style="padding:8px">
        场景为空 — 在「3D 生成」完成后自动建立节点。
      </div>
    </aside>

    <!-- 3D 视口 -->
    <div style="flex:1;display:flex;flex-direction:column;min-width:0">
      <div style="height:40px;background:var(--panel);border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:8px;padding:0 12px;flex:none">
        <button v-for="g in [['translate','G 移动'],['rotate','R 旋转'],['scale','S 缩放']]" :key="g[0]"
                class="btn" :style="{height:'26px',color:gizmoMode===g[0]?'#fff':'var(--dim)',background:gizmoMode===g[0]?'var(--acc)':'var(--panel2)'}"
                @click="gizmoMode=g[0]">{{ g[1] }}</button>
        <span style="width:1px;height:18px;background:var(--bd)"></span>
        <button class="btn" :style="{height:'26px',color:showGhost?'var(--tx)':'var(--dim)'}" @click="showGhost=!showGhost; rebuild()">原画对齐</button>
        <span class="mini" style="margin-left:auto">相机锁定为原画内参 · 拖拽结束才写 scene.json</span>
      </div>
      <div ref="viewport" style="flex:1;position:relative;background:#0b0d12;overflow:hidden"></div>
    </div>

    <!-- 变换检查器 -->
    <aside v-if="selectedId" style="width:240px;background:var(--panel);border-left:1px solid var(--bd);padding:12px;display:flex;flex-direction:column;gap:8px;flex:none;overflow:auto">
      <b style="font-weight:600">{{ scene.nodes.find(n=>n.node_id===selectedId)?.label || selectedId }}</b>
      <template v-if="scene.nodes.find(n=>n.node_id===selectedId)">
        <div class="kv"><span>源 PLY</span><b class="mini">{{ scene.nodes.find(n=>n.node_id===selectedId)?.source_ply }}</b></div>
        <div class="kv"><span>位置</span><b class="mini">{{ scene.nodes.find(n=>n.node_id===selectedId)?.transform.translation.map(n=>n.toFixed(2)).join(', ') }}</b></div>
        <div class="kv"><span>缩放</span><b class="mini">{{ scene.nodes.find(n=>n.node_id===selectedId)?.transform.scale.map(n=>n.toFixed(2)).join(', ') }}</b></div>
        <div class="kv"><span>关键帧</span><b>{{ Object.keys(scene.nodes.find(n=>n.node_id===selectedId)?.keyframes || {}).join(', ') || '—' }}</b></div>
      </template>
      <button class="btn" @click="() => {
        const n = scene.nodes.find(x=>x.node_id===selectedId)
        if (!n) return
        api.patchScene(project.project_id, [{ node_id: n.node_id, add_keyframe: 'kf-' + Object.keys(n.keyframes).length }])
          .then(() => { emit('notify','关键帧位姿已记录','ok'); loadScene() })
          .catch(e => emit('notify-error', e))
      }">关键帧+ 记录当前位姿</button>
      <button class="btn pri" :disabled="snapshotting" @click="snapshot">
        {{ snapshotting ? '渲染中…' : '快照渲染 (RGB+深度+边缘)' }}
      </button>
      <div class="mini">快照写入 stage3/keyframes/ 三联图, 供关键帧页与合成使用。</div>
    </aside>
  </div>
</template>
