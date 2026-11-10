<script setup>
// 论文 demo 页 (docs/paintingstudio_desktop_demo.md §5):
// 设备面板 + 三步时间线 + 产物画廊 (overlay/depth/PLY 下载)
import { ref, computed, onMounted } from 'vue'
import { t } from '../i18n.js'

const device = ref(null)          // GET /api/demo/device
const paintings = ref([])
const selectedPainting = ref(null)
const prefer = ref('auto')        // auto | gpu | cpu | mock
const running = ref(false)
const lastRun = ref(null)         // {run_id, device:{steps...}}
const runs = ref([])
const connError = ref(false)      // 服务不可达 → 显式横幅, 不再伪装成空状态

const tierColor = { gpu: 'var(--grn)', cpu: 'var(--yel)', mock: 'var(--red)' }
const tierName = computed(() => ({ gpu: 'GPU', cpu: 'CPU', mock: 'MOCK' }))

async function loadDevice() {
  try {
    const r = await fetch(`/api/demo/device?prefer=${prefer.value}`)
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    device.value = await r.json()
  } catch { connError.value = true }
}
async function loadPaintings() {
  try {
    const r = await fetch('/api/demo/paintings')
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    paintings.value = await r.json()
    if (paintings.value.length && !selectedPainting.value)
      selectedPainting.value = paintings.value[0].name
  } catch { connError.value = true }
}
async function loadRuns() {
  try {
    const r = await fetch('/api/demo/runs')
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    runs.value = await r.json()
  } catch { connError.value = true }
}

async function retryAll() {
  connError.value = false
  await Promise.all([loadDevice(), loadPaintings(), loadRuns()])
}

async function runDemo() {
  if (!selectedPainting.value) return
  running.value = true
  lastRun.value = null
  try {
    const r = await fetch('/api/demo/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ painting: selectedPainting.value, prefer: prefer.value }),
    })
    const data = await r.json()
    if (!r.ok) throw new Error(data.detail || r.statusText)
    lastRun.value = data
  } catch (e) {
    alert(t('demoFailed', e.message))
  } finally { running.value = false }
  // demo 已成功: 之后的刷新失败只标连接横幅, 不误报为 demo 失败
  try {
    await loadDevice()
    await loadRuns()
  } catch { /* loadDevice/loadRuns 内部已置 connError */ }
}

function artifactUrl(runId, filename) {
  return `/api/demo/artifact/${runId}/${filename}`
}

const dev = computed(() => device.value || { report: {} })
onMounted(retryAll)
</script>

<template>
  <div style="flex:1;overflow:auto;padding:16px;display:flex;flex-direction:column;gap:14px">
    <!-- 标题区 -->
    <div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap">
      <h2 style="font-weight:600;font-size:16px">{{ t('demoTitle') }}</h2>
      <span class="mini">{{ t('demoSub') }}</span>
    </div>

    <!-- 服务未连接横幅 (fetch 失败时显式提示, 不再伪装空状态) -->
    <div v-if="connError"
         style="background:rgba(224,101,90,.12);border:1px solid var(--red);border-radius:10px;padding:12px;display:flex;gap:12px;align-items:center">
      <span style="color:var(--red);font-weight:500">{{ t('connError') }}</span>
      <span class="mini">{{ t('connErrorHint') }}</span>
      <button class="btn" style="margin-left:auto" @click="retryAll">{{ t('retry') }}</button>
    </div>

    <!-- 设备面板 -->
    <div style="background:var(--panel);border:1px solid var(--bd);border-radius:10px;padding:12px;display:flex;gap:16px;flex-wrap:wrap;align-items:center">
      <div style="display:flex;align-items:center;gap:8px">
        <span class="mini">{{ t('currentTier') }}</span>
        <span class="badge" :style="{background:'transparent',border:'1px solid '+tierColor[dev.effective],color:tierColor[dev.effective],fontSize:'12px',padding:'4px 12px'}">
          {{ tierName[dev.effective] || '…' }}
        </span>
        <span v-if="dev.reason" class="mini">{{ dev.reason }}</span>
      </div>
      <div class="mini" v-if="dev.report?.cuda_available">
        {{ t('cudaMode', dev.report.cuda_device_name, dev.report.vram_gb) }}
      </div>
      <div class="mini" v-else-if="dev.report?.torch_version">
        {{ t('cpuMode', dev.report.torch_version) }}
      </div>
      <div class="mini" v-else>{{ t('mockMode') }}</div>
      <!-- 档位选择 -->
      <div style="margin-left:auto;display:flex;gap:6px;align-items:center">
        <span class="mini">{{ t('inferDevice') }}</span>
        <select v-model="prefer" @change="loadDevice" style="padding:4px 8px">
          <option value="auto">{{ t('autoOpt') }}</option>
          <option value="gpu">{{ t('forceGpu') }}</option>
          <option value="cpu">{{ t('forceCpu') }}</option>
          <option value="mock">{{ t('forceMock') }}</option>
        </select>
      </div>
    </div>

    <!-- 后端矩阵 -->
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px">
      <div v-for="(b, key) in dev.report?.backends || {}" :key="key"
           style="background:var(--panel);border:1px solid var(--bd);border-radius:10px;padding:10px;display:flex;flex-direction:column;gap:4px">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <b style="font-weight:500">{{ key === 'segment' ? t('segCard') : t('depCard') }}</b>
          <span class="badge" :class="b.device === 'gpu' ? 'ok' : b.device === 'cpu' ? 'warn' : 'bad'">
            {{ b.kind }}:{{ b.device }}
          </span>
        </div>
        <span class="mini">{{ b.detail }}</span>
        <span v-if="b.infer_ms" class="mini tabular-nums">{{ t('lastInfer', b.infer_ms) }}</span>
      </div>
    </div>

    <!-- 运行控制 -->
    <div style="background:var(--panel);border:1px solid var(--bd);border-radius:10px;padding:12px;display:flex;gap:12px;align-items:center;flex-wrap:wrap">
      <span class="mini">{{ t('samplePainting') }}</span>
      <select v-model="selectedPainting" style="padding:4px 8px;min-width:160px">
        <option v-for="p in paintings" :key="p.name" :value="p.name">{{ p.name }} ({{ p.width }}×{{ p.height }})</option>
      </select>
      <button class="btn pri" :disabled="running || !selectedPainting" @click="runDemo">
        {{ running ? t('demoRunning') : t('runDemo') }}
      </button>
      <span v-if="lastRun" class="mini">
        {{ t('totalTime') }} <b class="tabular-nums" style="color:var(--tx)">{{ lastRun.device.total_ms }} ms</b>
        · {{ lastRun.device.device_requested }} → {{ tierName[lastRun.device.device_effective] || lastRun.device.device_effective }}
      </span>
    </div>

    <!-- 三步时间线 -->
    <div v-if="lastRun" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px">
      <div v-for="(s, i) in lastRun.device.steps" :key="i"
           style="background:var(--panel);border:1px solid var(--bd);border-radius:10px;padding:10px;display:flex;flex-direction:column;gap:6px">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <b style="font-weight:500;font-size:12px">STEP {{ i+1 }} · {{ s.name }}</b>
          <span class="badge ok tabular-nums" v-if="s.ok">{{ s.ms }} ms</span>
        </div>
        <span class="mini">{{ s.summary }}</span>
        <img v-if="s.artifacts?.overlay || s.artifacts?.depth_vis"
             :src="artifactUrl(lastRun.run_id, s.artifacts.overlay || s.artifacts.depth_vis)"
             style="width:100%;border-radius:6px;max-height:150px;object-fit:contain;background:#0b0d12" alt="artifact" />
      </div>
    </div>

    <!-- PLY 下载 + 历史 -->
    <div v-if="lastRun" style="display:flex;gap:10px;flex-wrap:wrap">
      <a class="btn" :href="artifactUrl(lastRun.run_id, 'scene.ply')" download="scene.ply">
        {{ t('downloadPly') }}
      </a>
      <a class="btn" :href="artifactUrl(lastRun.run_id, 'overlay.png')" download="overlay.png">
        {{ t('downloadOverlay') }}
      </a>
      <a class="btn" :href="artifactUrl(lastRun.run_id, 'depth_vis.png')" download="depth_vis.png">
        {{ t('downloadDepth') }}
      </a>
    </div>

    <div v-if="runs.length" style="background:var(--panel);border:1px solid var(--bd);border-radius:10px;padding:10px">
      <b style="font-weight:500;font-size:12px">{{ t('runHistory') }}</b>
      <div v-for="r in runs.slice(0, 8)" :key="r.run_id"
           class="mini" style="display:flex;gap:12px;padding:3px 0;align-items:center">
        <span class="tabular-nums">{{ r.run_id }}</span>
        <span :style="{color: tierColor[r.device.device_effective]}">{{ tierName[r.device.device_effective] }}</span>
        <span class="tabular-nums">{{ r.device.total_ms }} ms</span>
        <span>{{ r.painting }}</span>
        <span style="margin-left:auto;opacity:.7">{{ new Date(r.ts).toLocaleString() }}</span>
      </div>
    </div>

    <div v-if="!paintings.length && !connError" class="empty">{{ t('noPainting') }}</div>
  </div>
</template>
