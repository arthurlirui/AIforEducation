<script setup>
// 语义分割审校 (§4.2): mask 叠加 + 笔刷修补 + 误检标记 + 深度视图
import { ref, computed, onMounted } from 'vue'
import { api, waitTask } from '../api.js'
import { t } from '../i18n.js'

const props = defineProps({ project: Object })
const emit = defineEmits(['notify', 'notify-error', 'refresh'])

const objects = ref([])
const selected = ref(null)      // ObjectMeta
const view = ref('ov')          // ov | src | msk | dep
const brushMode = ref('none')   // none | draw | erase
const brushSize = ref(10)
const running = ref(false)
const progress = ref(0)

const maskImages = ref({})      // oid -> mask URL (cache-busted by version)
const overlayOpacity = ref(0.45)

async function loadObjects() {
  try {
    objects.value = await api.listObjects(props.project.project_id)
    if (!selected.value && objects.value.length) select(objects.value[0])
  } catch (e) { emit('notify-error', e) }
}

function select(o) {
  selected.value = o
  const pid = props.project.project_id
  if (maskImages.value[o.object_id] === undefined) {
    maskImages.value[o.object_id] = api.maskUrl(pid, o.object_id)
  }
}

async function runSegment() {
  running.value = true; progress.value = 0
  try {
    const { task_id } = await api.runSegment(props.project.project_id)
    const tk = await waitTask(task_id, x => { progress.value = x.progress })
    if (tk.status === 'done') {
      emit('notify', t('segDone', tk.result.num_objects, tk.result.detector), 'ok')
      await loadObjects(); emit('refresh')
    } else emit('notify', t('segFailed', tk.error || tk.status), 'err')
  } catch (e) { emit('notify-error', e) }
  finally { running.value = false }
}

async function toggleRejected(o) {
  try {
    const updated = await api.updateObject(props.project.project_id, o.object_id,
                                           { rejected: !o.rejected })
    Object.assign(o, updated)
    emit('notify', updated.rejected ? t('rejectedToast', o.label) : t('restoredToast', o.label), 'ok')
  } catch (e) { emit('notify-error', e) }
}

// ── 笔刷 (canvas 叠加) ──
const canvasRef = ref(null)
const strokes = ref([])
let painting = false

function canvasPos(e) {
  const c = canvasRef.value
  const r = c.getBoundingClientRect()
  return { x: (e.clientX - r.left) / r.width * c.width,
           y: (e.clientY - r.top) / r.height * c.height }
}
function onDown(e) {
  if (brushMode.value === 'none' || !selected.value) return
  painting = true
  const p = canvasPos(e)
  strokes.value.push({ x: Math.round(p.x), y: Math.round(p.y),
                       radius: brushSize.value, erase: brushMode.value === 'erase' })
}
function onMove(e) {
  if (!painting) return
  const p = canvasPos(e)
  strokes.value.push({ x: Math.round(p.x), y: Math.round(p.y),
                       radius: brushSize.value, erase: brushMode.value === 'erase' })
}
function onUp() {
  if (!painting) return
  painting = false
  commitStrokes()
}
async function commitStrokes() {
  const pid = props.project.project_id
  const o = selected.value
  const c = canvasRef.value
  const scaleX = props.project.painting.width / c.width
  const scaleY = props.project.painting.height / c.height
  const payload = strokes.value.map(s => ({
    x: Math.round(s.x * scaleX), y: Math.round(s.y * scaleY),
    radius: Math.max(1, Math.round(s.radius * scaleX)), erase: s.erase,
  }))
  strokes.value = []
  try {
    const r = await api.paintMask(pid, o.object_id, { strokes: payload })
    o.mask_version = r.mask_version
    maskImages.value[o.object_id] = api.maskUrl(pid, o.object_id) + `?v=${o.mask_version}`
    emit('notify', t('maskUpdated', r.mask_version), 'ok')
  } catch (e) { emit('notify-error', e) }
}

const viewSrc = computed(() => {
  const pid = props.project.project_id
  return { ov: api.paintingUrl(pid), src: api.paintingUrl(pid),
           msk: selected.value ? maskImages.value[selected.value.object_id] : '',
           dep: api.depthUrl(pid) }[view.value]
})

onMounted(loadObjects)
</script>

<template>
  <div style="flex:1;display:flex;min-width:0">
    <!-- 物体列表 -->
    <aside style="width:210px;background:var(--panel);border-right:1px solid var(--bd);padding:10px;display:flex;flex-direction:column;gap:4px;flex:none;overflow:auto">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
        <b style="font-weight:600">{{ t('objects') }} ({{ objects.length }})</b>
        <button class="btn" style="height:24px;padding:0 8px;font-size:11px" :disabled="running"
                @click="runSegment">{{ running ? `${Math.round(progress*100)}%` : t('resegment') }}</button>
      </div>
      <div v-if="running" class="pbar"><i :style="{width: progress*100+'%'}"></i></div>
      <button v-for="o in objects" :key="o.object_id"
              :style="{ display:'flex', alignItems:'center', gap:'8px', padding:'7px 8px', borderRadius:'7px', width:'100%', textAlign:'left',
                color: selected && selected.object_id===o.object_id ? 'var(--tx)' : 'var(--dim)',
                background: selected && selected.object_id===o.object_id ? 'var(--panel2)' : 'transparent',
                textDecoration: o.rejected ? 'line-through' : 'none', opacity: o.rejected ? .5 : 1 }"
              @click="select(o)">
        <span :style="{width:'12px',height:'12px',borderRadius:'4px',flex:'none',background:o.color}"></span>
        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ o.label }} #{{ o.object_id }}</span>
        <span class="mini" style="margin-left:auto">{{ o.confidence.toFixed(2) }}</span>
      </button>
      <div v-if="!objects.length && !running" class="mini" style="padding:8px">
        {{ t('noObjects') }}
      </div>
    </aside>

    <!-- 视口 -->
    <div style="flex:1;display:flex;flex-direction:column;min-width:0">
      <div style="height:40px;background:var(--panel);border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:8px;padding:0 12px;flex:none">
        <button v-for="v in [['ov','viewOverlay'],['src','viewSource'],['msk','viewMask'],['dep','viewDepth']]" :key="v[0]"
                class="btn" :style="{height:'26px', color:view===v[0]?'#fff':'var(--dim)', background:view===v[0]?'var(--acc)':'var(--panel2)'}"
                @click="view=v[0]">{{ t(v[1]) }}</button>
        <template v-if="view==='ov'">
          <span style="width:1px;height:18px;background:var(--bd)"></span>
          <button class="btn" :style="{height:'26px',color:brushMode==='draw'?'#fff':'var(--dim)',background:brushMode==='draw'?'var(--acc)':'var(--panel2)'}"
                  @click="brushMode = brushMode==='draw' ? 'none' : 'draw'">{{ t('brush') }}</button>
          <button class="btn" :style="{height:'26px',color:brushMode==='erase'?'#fff':'var(--dim)',background:brushMode==='erase'?'var(--acc)':'var(--panel2)'}"
                  @click="brushMode = brushMode==='erase' ? 'none' : 'erase'">{{ t('eraser') }}</button>
          <label class="mini" style="display:flex;align-items:center;gap:6px">
            {{ t('radius') }} <input type="range" min="2" max="30" v-model.number="brushSize" style="width:80px"> {{ brushSize }}
          </label>
          <label class="mini" style="display:flex;align-items:center;gap:6px">
            {{ t('opacity') }} <input type="range" min="10" max="90" v-model.number="overlayOpacity" style="width:80px">
          </label>
        </template>
        <span class="mini" style="margin-left:auto">{{ t('brushHint') }}</span>
      </div>

      <div style="flex:1;position:relative;background:#0b0d12;overflow:hidden;display:flex;align-items:center;justify-content:center">
        <div v-if="!viewSrc" class="empty">{{ t('noObjects') }}</div>
        <template v-else>
          <img :src="viewSrc" style="max-width:100%;max-height:100%;object-fit:contain" alt="viewport" />
          <img v-if="view==='ov' && selected && maskImages[selected.object_id] && !selected.rejected"
               :src="maskImages[selected.object_id]"
               :style="{ position:'absolute', maxWidth:'100%', maxHeight:'100%', objectFit:'contain',
                         opacity: overlayOpacity/100,
                         mixBlendMode: 'screen', pointerEvents:'none' }" alt="mask overlay" />
          <canvas v-show="view==='ov' && brushMode!=='none'"
                  ref="canvasRef"
                  :width="project.painting.width" :height="project.painting.height"
                  :style="{ position:'absolute', maxWidth:'100%', maxHeight:'100%', objectFit:'contain',
                            cursor: brushMode==='erase' ? 'cell' : 'crosshair' }"
                  @mousedown="onDown" @mousemove="onMove" @mouseup="onUp" @mouseleave="onUp"></canvas>
        </template>
      </div>
    </div>

    <!-- 检查器 -->
    <aside v-if="selected" style="width:236px;background:var(--panel);border-left:1px solid var(--bd);padding:12px;display:flex;flex-direction:column;gap:8px;flex:none;overflow:auto">
      <b style="font-weight:600">{{ selected.label }} #{{ selected.object_id }}</b>
      <div class="kv"><span>{{ t('category') }}</span><b>{{ selected.category }}</b></div>
      <div class="kv"><span>{{ t('confidence') }}</span><b>{{ selected.confidence.toFixed(3) }}</b></div>
      <div class="kv"><span>bbox</span><b class="mini">{{ selected.bbox.join(', ') }}</b></div>
      <div class="kv"><span>{{ t('maskVersion') }}</span><b>v{{ selected.mask_version }}</b></div>
      <div class="kv"><span>{{ t('gsVersion') }}</span><b>{{ selected.gs_version ? 'v'+selected.gs_version : t('notGenerated') }}</b></div>
      <div class="kv"><span>{{ t('depthRange') }}</span><b class="mini">{{ selected.depth_range.map(n=>n.toFixed(2)).join(' – ') }}</b></div>
      <div v-if="selected.gs_source_ply && selected.mask_version > 1 && selected.gs_version"
           class="badge warn" style="align-self:flex-start">
        {{ t('staleMask') }} <a href="#" @click.prevent="emit('notify', t('rerunGs'))" style="color:var(--yel)">{{ t('rerunGs') }}</a>
      </div>
      <button class="btn" :class="selected.rejected ? '' : 'danger'" @click="toggleRejected(selected)">
        {{ selected.rejected ? t('restoreObject') : t('markRejected') }}
      </button>
      <div class="mini">{{ t('rejectedHint') }}</div>
    </aside>
  </div>
</template>
