<script setup>
// 关键帧与线稿 (§4.5): 快照列表 + 线稿绘制
import { ref, onMounted } from 'vue'
import { api } from '../api.js'

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
    if (keyframes.value.length && !selected.value) selected.value = keyframes.value[0]
  } catch (e) { emit('notify-error', e) }
}

function select(kf) {
  selected.value = kf
  // 等底图加载后初始化画布
  setTimeout(() => {
    const c = canvasRef.value
    if (!c) return
    const img = new Image()
    img.onload = () => {
      c.width = img.width; c.height = img.height
      ctx = c.getContext('2d')
      ctx.drawImage(img, 0, 0)
    }
    img.src = api.keyframeUrl(props.project.project_id, kf.keyframe_id, 'rgb')
  }, 50)
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
    emit('notify', `线稿已保存: ${selected.value.keyframe_id}`, 'ok')
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
      <b style="font-weight:600">关键帧 ({{ keyframes.length }})</b>
      <button v-for="kf in keyframes" :key="kf.keyframe_id"
              :style="{ display:'flex', alignItems:'center', gap:'8px', padding:'7px 8px', borderRadius:'7px', width:'100%', textAlign:'left',
                color: selected && selected.keyframe_id===kf.keyframe_id ? 'var(--tx)' : 'var(--dim)',
                background: selected && selected.keyframe_id===kf.keyframe_id ? 'var(--panel2)' : 'transparent' }"
              @click="select(kf)">
        <img :src="api.keyframeUrl(project.project_id, kf.keyframe_id, 'rgb')"
             style="width:44px;height:30px;object-fit:cover;border-radius:4px" alt="关键帧" />
        <span>
          {{ kf.keyframe_id }}
          <small class="mini" style="display:block">{{ kf.source === 'snapshot' ? '快照' : '手绘' }}</small>
        </span>
      </button>
      <div v-if="!keyframes.length" class="mini" style="padding:8px">
        暂无关键帧 — 在「场景组装」移动物体后点击「快照渲染」。
      </div>
      <div class="mini" style="margin-top:8px">
        色标: <span :style="{color:'#5b8cff'}">━ 轮廓线</span>
        <span :style="{color:'#e0655a'}" style="margin-left:6px">━ 运动线</span>
      </div>
    </aside>

    <!-- 绘制画布 -->
    <div style="flex:1;display:flex;flex-direction:column;min-width:0">
      <div style="height:40px;background:var(--panel);border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:8px;padding:0 12px;flex:none">
        <button class="btn" :style="{height:'26px',color:brushColor==='#5b8cff'?'#fff':'var(--dim)',background:brushColor==='#5b8cff'?'var(--acc)':'var(--panel2)'}"
                @click="brushColor='#5b8cff'">轮廓线</button>
        <button class="btn" :style="{height:'26px',color:brushColor==='#e0655a'?'#fff':'var(--dim)',background:brushColor==='#e0655a'?'var(--acc)':'var(--panel2)'}"
                @click="brushColor='#e0655a'">运动线</button>
        <label class="mini" style="display:flex;align-items:center;gap:6px">
          线宽 <input type="range" min="1" max="10" v-model.number="brushSize" style="width:70px">
        </label>
        <button class="btn" style="height:26px" @click="clearCanvas">清空重画</button>
        <button class="btn pri" style="height:26px;margin-left:auto" :disabled="saving || !selected" @click="saveLineart">
          {{ saving ? '保存中…' : '保存线稿' }}
        </button>
      </div>
      <div style="flex:1;position:relative;background:#0b0d12;display:flex;align-items:center;justify-content:center;overflow:hidden">
        <div v-if="!selected" class="empty">选择或生成关键帧</div>
        <canvas v-else ref="canvasRef"
                style="max-width:100%;max-height:100%;object-fit:contain;cursor:crosshair"
                @mousedown="onDown" @mousemove="onMove" @mouseup="onUp" @mouseleave="onUp"></canvas>
      </div>
    </div>
  </div>
</template>
