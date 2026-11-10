<script setup>
// 场景组装编辑器 (§4.4): Three.js 视口 + 变换 gizmo + 大纲树 + 快照
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { api, waitTask } from '../api.js'
import { initScene, disposeScene } from '../three.js'
import { t } from '../i18n.js'

const props = defineProps({ project: Object })
const emit = defineEmits(['notify', 'notify-error', 'refresh'])

const scene = ref({ nodes: [], camera: {} })
const selectedId = ref(null)
const gizmoMode = ref('translate')   // translate | rotate | scale
const showGhost = ref(true)
const snapshotting = ref(false)
let snapshotTaskId = null

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
    const oid = Number(n.node_id.split('-')[1])
    if (!Number.isInteger(oid)) { console.warn('SceneView: 无法从 node_id 提取物体 id, 跳过节点', n.node_id); continue }
    three.addObject(n, api.plyUrl(pid, oid))
  }
  three.setGhost(showGhost.value ? api.paintingUrl(pid) : null)
}

// Three.js → PATCH /scene (拖拽结束提交, §3.4 写入协议)
function onTransformEnd(nodeId, transform) {
  const node = scene.value.nodes.find(n => n.node_id === nodeId)
  if (!node) return
  node.transform = transform
  api.patchScene(props.project.project_id, [{ node_id: nodeId, transform }])
    .then(() => emit('notify', t('sceneUpdated', nodeId), 'ok'))
    .catch(e => emit('notify-error', e))
}

async function toggleVisible(n) {
  try {
    await api.patchScene(props.project.project_id, [{ node_id: n.node_id, visible: !n.visible }])
    n.visible = !n.visible
    rebuild()
  } catch (e) { emit('notify-error', e) }
}

async function addKeyframe() {
  const n = scene.value.nodes.find(x => x.node_id === selectedId.value)
  if (!n) return
  try {
    await api.patchScene(props.project.project_id,
      [{ node_id: n.node_id, add_keyframe: 'kf-' + Object.keys(n.keyframes).length }])
    emit('notify', t('kfRecorded'), 'ok')
    await loadScene()
  } catch (e) { emit('notify-error', e) }
}

async function snapshot() {
  snapshotting.value = true
  try {
    const { task_id } = await api.snapshot(props.project.project_id)
    snapshotTaskId = task_id
    const tk = await waitTask(task_id)
    if (tk.status === 'done') {
      emit('notify', t('snapshotDone', tk.result.keyframe_id, tk.result.moved), 'ok')
      emit('refresh')
    } else emit('notify', t('snapshotFailed', tk.error), 'err')
  } catch (e) { emit('notify-error', e) }
  finally { snapshotting.value = false; snapshotTaskId = null }
}

async function cancelSnapshot() {
  if (!snapshotTaskId) return
  try { await api.cancelTask(snapshotTaskId) } catch (e) { emit('notify-error', e) }
}

watch(gizmoMode, m => three && three.setGizmoMode(m))
watch(selectedId, id => three && three.select(id))

onMounted(async () => {
  three = initScene(viewport.value, {
    onTransformEnd,
    onSelect: id => { selectedId.value = id },
    onPlyError: (nodeId, url) => emit('notify-error', new Error(`PLY 加载失败: ${nodeId} (${url})`)),
  })
  await loadScene()
})
onBeforeUnmount(() => { disposeScene(three); three = null })
</script>

<template>
  <div style="flex:1;display:flex;min-width:0">
    <!-- 大纲树 -->
    <aside style="width:220px;background:var(--panel);border-right:1px solid var(--bd);padding:10px;display:flex;flex-direction:column;gap:4px;flex:none;overflow:auto">
      <b style="font-weight:600;margin-bottom:2px">{{ t('outline') }}</b>
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
        {{ t('sceneEmpty') }}
      </div>
    </aside>

    <!-- 3D 视口 -->
    <div style="flex:1;display:flex;flex-direction:column;min-width:0">
      <div style="height:40px;background:var(--panel);border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:8px;padding:0 12px;flex:none">
        <button v-for="g in [['translate','gizmoMove'],['rotate','gizmoRotate'],['scale','gizmoScale']]" :key="g[0]"
                class="btn" :style="{height:'26px',color:gizmoMode===g[0]?'#fff':'var(--dim)',background:gizmoMode===g[0]?'var(--acc)':'var(--panel2)'}"
                @click="gizmoMode=g[0]">{{ t(g[1]) }}</button>
        <span style="width:1px;height:18px;background:var(--bd)"></span>
        <button class="btn" :style="{height:'26px',color:showGhost?'var(--tx)':'var(--dim)'}" @click="showGhost=!showGhost; rebuild()">{{ t('ghostAlign') }}</button>
        <span class="mini" style="margin-left:auto">{{ t('ghostHint') }}</span>
      </div>
      <div ref="viewport" style="flex:1;position:relative;background:#0b0d12;overflow:hidden"></div>
    </div>

    <!-- 变换检查器 -->
    <aside v-if="selectedId" style="width:240px;background:var(--panel);border-left:1px solid var(--bd);padding:12px;display:flex;flex-direction:column;gap:8px;flex:none;overflow:auto">
      <b style="font-weight:600">{{ scene.nodes.find(n=>n.node_id===selectedId)?.label || selectedId }}</b>
      <template v-if="scene.nodes.find(n=>n.node_id===selectedId)">
        <div class="kv"><span>{{ t('sourcePly') }}</span><b class="mini">{{ scene.nodes.find(n=>n.node_id===selectedId)?.source_ply }}</b></div>
        <div class="kv"><span>{{ t('position') }}</span><b class="mini">{{ scene.nodes.find(n=>n.node_id===selectedId)?.transform.translation.map(n=>n.toFixed(2)).join(', ') }}</b></div>
        <div class="kv"><span>{{ t('scale') }}</span><b class="mini">{{ scene.nodes.find(n=>n.node_id===selectedId)?.transform.scale.map(n=>n.toFixed(2)).join(', ') }}</b></div>
        <div class="kv"><span>{{ t('keyframes') }}</span><b>{{ Object.keys(scene.nodes.find(n=>n.node_id===selectedId)?.keyframes || {}).join(', ') || '—' }}</b></div>
      </template>
      <button class="btn" @click="addKeyframe">{{ t('addKf') }}</button>
      <button class="btn pri" :disabled="snapshotting" @click="snapshot">
        {{ snapshotting ? t('snapshotting') : t('snapshotBtn') }}
      </button>
      <button v-if="snapshotting" class="btn" style="color:var(--red)" @click="cancelSnapshot">
        {{ t('cancelTask') }}
      </button>
      <div class="mini">{{ t('snapshotHint') }}</div>
    </aside>
  </div>
</template>
