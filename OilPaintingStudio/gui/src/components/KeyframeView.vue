<script setup>
// 关键帧与线稿 (§4.5): 快照列表 + 线稿绘制
import { ref, onMounted, nextTick } from 'vue'
import { api } from '../api.js'
import { t } from '../i18n.js'

const props = defineProps({ project: Object })
const emit = defineEmits(['notify', 'notify-error', 'refresh'])

const keyframes = ref([])
const selected = ref(null)
const brushColor = ref('#5b8cff')   // 轮廓线 / 运动线双色语义
const brushSize = ref(3)
const saving = ref(false)

const canvasRef = ref(null)
let ctx = null
let drawing = false

async function load() {
  try {
    keyframes.value = await api.listKeyframes(props.project.project_id)
    if (keyframes.value.length && !selected.value) select(keyframes.value[0])
  } catch (e) { emit('notify-error', e) }
}

let selectSeq = 0  // 请求序号守卫: 快速切换时只认最后一次 select

function select(kf) {
  selected.value = kf
  const seq = ++selectSeq
  nextTick(() => {
    if (seq !== selectSeq) return  // 已被更晚的 select 取代
    const c = canvasRef.value
    if (!c) return
    const img = new Image()
    img.onload = () => {
      if (seq !== selectSeq) return  // 竞态: 后完成的旧图不覆盖新选择
      c.width = img.width; c.height = img.height
      ctx = c.getContext('2d')
      ctx.drawImage(img, 0, 0)
    }
    img.src = api.keyframeUrl(props.project.project_id, kf.keyframe_id, 'rgb')
  })
}

function pos(e) {
  const c = canvasRef.value, r = c.getBoundingClientRect()
  return { x: (e.clientX - r.left) / r.width * c.width,
           y: (e.clientY - r.top) / r.height * c.height }
}
function onDown(e) {
  if (!ctx) return
  drawing = true
  const p = pos(e)
  ctx.strokeStyle = brushColor.value
  ctx.lineWidth = brushSize.value
  ctx.lineCap = 'round'
  ctx.beginPath()
  ctx.moveTo(p.x, p.y)
}
function onMove(e) {
  if (!drawing) return
  const p = pos(e)
  ctx.lineTo(p.x, p.y)
  ctx.stroke()
}
function onUp() { drawing = false }
function clearCanvas() {
  if (!ctx || !selected.value) return
  select(selected.value)   // 重画底图
}

async function saveLineart() {
  if (!canvasRef.value || !selected.value) return
  saving.value = true
  try {
    const dataUrl = canvasRef.value.toDataURL('image/png')
    const b64 = dataUrl.split(',')[1]
    await api.uploadLineart(props.project.project_id, selected.value.keyframe_id, b64)
    emit('notify', t('lineartSaved', selected.value.keyframe_id), 'ok')
    await load()
  } catch (e) { emit('notify-error', e) }
  finally { saving.value = false }
}

onMounted(load)
</script>

<template>
  <div style="flex:1;display:flex;min-width:0">
    <!-- 关键帧列表 -->
    <aside style="width:210px;background:var(--panel);border-right:1px solid var(--bd);padding:10px;display:flex;flex-direction:column;gap:6px;flex:none;overflow:auto">
      <b style="font-weight:600">{{ t('keyframes') }} ({{ keyframes.length }})</b>
      <button v-for="kf in keyframes" :key="kf.keyframe_id"
              :style="{ display:'flex', alignItems:'center', gap:'8px', padding:'7px 8px', borderRadius:'7px', width:'100%', textAlign:'left',
                color: selected && selected.keyframe_id===kf.keyframe_id ? 'var(--tx)' : 'var(--dim)',
                background: selected && selected.keyframe_id===kf.keyframe_id ? 'var(--panel2)' : 'transparent' }"
              @click="select(kf)">
        <img :src="api.keyframeUrl(project.project_id, kf.keyframe_id, 'rgb')"
             style="width:44px;height:30px;object-fit:cover;border-radius:4px" alt="keyframe" />
        <span>
          {{ kf.keyframe_id }}
          <small class="mini" style="display:block">{{ kf.source === 'snapshot' ? t('srcSnapshot') : t('srcHandDrawn') }}</small>
        </span>
      </button>
      <div v-if="!keyframes.length" class="mini" style="padding:8px">
        {{ t('noKf') }}
      </div>
      <div class="mini" style="margin-top:8px">
        {{ t('legend') }}: <span :style="{color:'#5b8cff'}">━ {{ t('contourLine') }}</span>
        <span :style="{color:'#e0655a'}" style="margin-left:6px">━ {{ t('motionLine') }}</span>
      </div>
    </aside>

    <!-- 绘制画布 -->
    <div style="flex:1;display:flex;flex-direction:column;min-width:0">
      <div style="height:40px;background:var(--panel);border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:8px;padding:0 12px;flex:none">
        <button class="btn" :style="{height:'26px',color:brushColor==='#5b8cff'?'#fff':'var(--dim)',background:brushColor==='#5b8cff'?'var(--acc)':'var(--panel2)'}"
                @click="brushColor='#5b8cff'">{{ t('contourLine') }}</button>
        <button class="btn" :style="{height:'26px',color:brushColor==='#e0655a'?'#fff':'var(--dim)',background:brushColor==='#e0655a'?'var(--acc)':'var(--panel2)'}"
                @click="brushColor='#e0655a'">{{ t('motionLine') }}</button>
        <label class="mini" style="display:flex;align-items:center;gap:6px">
          {{ t('lineWidth') }} <input type="range" min="1" max="10" v-model.number="brushSize" style="width:70px">
        </label>
        <button class="btn" style="height:26px" @click="clearCanvas">{{ t('clearCanvas') }}</button>
        <button class="btn pri" style="height:26px;margin-left:auto" :disabled="saving || !selected" @click="saveLineart">
          {{ saving ? t('savingLineart') : t('saveLineart') }}
        </button>
      </div>
      <div style="flex:1;position:relative;background:#0b0d12;display:flex;align-items:center;justify-content:center;overflow:hidden">
        <div v-if="!selected" class="empty">{{ t('selectKf') }}</div>
        <canvas v-else ref="canvasRef"
                style="max-width:100%;max-height:100%;object-fit:contain;cursor:crosshair"
                @mousedown="onDown" @mousemove="onMove" @mouseup="onUp" @mouseleave="onUp"></canvas>
      </div>
    </div>
  </div>
</template>
