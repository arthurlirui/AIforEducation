<script setup>
// 论文 demo 页 (设计文档 docs/paintingstudio_desktop_demo.md §5):
// 设备面板 + 三步时间线 + 产物画廊 (overlay/depth/PLY 三视图)
import { ref, computed, onMounted } from 'vue'
import { api, waitTask } from '../api.js'

const device = ref(null)          // GET /api/demo/device
const paintings = ref([])
const selectedPainting = ref(null)
const prefer = ref('auto')        // auto | gpu | cpu | mock
const running = ref(false)
const lastRun = ref(null)         // {run_id, device:{steps...}}
const runs = ref([])

const tierColor = { gpu: 'var(--grn)', cpu: 'var(--yel)', mock: 'var(--red)' }
const tierName = { gpu: 'GPU', cpu: 'CPU', mock: 'MOCK' }

async function loadDevice() {
  const r = await fetch(`/api/demo/device?prefer=${prefer.value}`)
  device.value = await r.json()
}
async function loadPaintings() {
  const r = await fetch('/api/demo/paintings')
  paintings.value = await r.json()
  if (paintings.value.length && !selectedPainting.value)
    selectedPainting.value = paintings.value[0].name
}
async function loadRuns() {
  const r = await fetch('/api/demo/runs')
  runs.value = await r.json()
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
    await loadDevice()
    await loadRuns()
  } catch (e) {
    alert(`demo 失败: ${e.message}`)
  } finally { running.value = false }
}

function artifactUrl(runId, filename) {
  return `/api/demo/artifact/${runId}/${filename}`
}

const dev = computed(() => device.value || { report: {} })
onMounted(async () => {
  await loadDevice()
  await loadPaintings()
  await loadRuns()
})
</script>

<template>
  <div style="flex:1;overflow:auto;padding:16px;display:flex;flex-direction:column;gap:14px">
    <!-- 标题区 -->
    <div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap">
      <h2 style="font-weight:600;font-size:16px">PaintingStudio — 论文 Demo</h2>
      <span class="mini">Canvas3D · 语义分割 → 深度估计 → 3D 化身 · GPU/CPU/MOCK 自动回退</span>
    </div>

    <!-- 设备面板 -->
    <div style="background:var(--panel);border:1px solid var(--bd);border-radius:10px;padding:12px;display:flex;gap:16px;flex-wrap:wrap;align-items:center">
      <div style="display:flex;align-items:center;gap:8px">
        <span class="mini">当前档位</span>
        <span class="badge" :style="{background:'transparent',border:'1px solid '+tierColor[dev.effective],color:tierColor[dev.effective],fontSize:'12px',padding:'4px 12px'}">
          {{ tierName[dev.effective] || '…' }}
        </span>
        <span v-if="dev.reason" class="mini">{{ dev.reason }}</span>
      </div>
      <div class="mini" v-if="dev.report?.cuda_available">
        CUDA: {{ dev.report.cuda_device_name }} · {{ dev.report.vram_gb }} GB
      </div>
      <div class="mini" v-else-if="dev.report?.torch_version">
        torch {{ dev.report.torch_version }} · CPU 模式
      </div>
      <div class="mini" v-else>torch 未安装 · mock 模式</div>
      <!-- 档位选择 -->
      <div style="margin-left:auto;display:flex;gap:6px;align-items:center">
        <span class="mini">推理设备</span>
        <select v-model="prefer" @change="loadDevice" style="padding:4px 8px">
          <option value="auto">自动</option>
          <option value="gpu">强制 GPU</option>
          <option value="cpu">强制 CPU</option>
          <option value="mock">强制 MOCK</option>
        </select>
      </div>
    </div>

    <!-- 后端矩阵 -->
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px">
      <div v-for="(b, key) in dev.report?.backends || {}" :key="key"
           style="background:var(--panel);border:1px solid var(--bd);border-radius:10px;padding:10px;display:flex;flex-direction:column;gap:4px">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <b style="font-weight:500">{{ key === 'segment' ? '语义分割 (PaintParse)' : '深度估计 (MonoDepth)' }}</b>
          <span class="badge" :class="b.device === 'gpu' ? 'ok' : b.device === 'cpu' ? 'warn' : 'bad'">
            {{ b.kind }}:{{ b.device }}
          </span>
        </div>
        <span class="mini">{{ b.detail }}</span>
        <span v-if="b.infer_ms" class="mini tabular-nums">上次推理 {{ b.infer_ms }} ms</span>
      </div>
    </div>

    <!-- 运行控制 -->
    <div style="background:var(--panel);border:1px solid var(--bd);border-radius:10px;padding:12px;display:flex;gap:12px;align-items:center;flex-wrap:wrap">
      <span class="mini">示例画作</span>
      <select v-model="selectedPainting" style="padding:4px 8px;min-width:160px">
        <option v-for="p in paintings" :key="p.name" :value="p.name">{{ p.name }} ({{ p.width }}×{{ p.height }})</option>
      </select>
      <img v-if="paintings.length" :src="`/api/demo/artifact/../paintings/${selectedPainting}/thumb.png`"
           style="height:40px;border-radius:4px" alt="缩略图" v-show="false" />
      <button class="btn pri" :disabled="running || !selectedPainting" @click="runDemo">
        {{ running ? '运行中…' : '▶ 运行 Demo' }}
      </button>
      <span v-if="lastRun" class="mini">
        总耗时 <b class="tabular-nums" style="color:var(--tx)">{{ lastRun.device.total_ms }} ms</b>
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
             style="width:100%;border-radius:6px;max-height:150px;object-fit:contain;background:#0b0d12" alt="步骤产物" />
      </div>
    </div>

    <!-- PLY 下载 + 历史 -->
    <div v-if="lastRun" style="display:flex;gap:10px;flex-wrap:wrap">
      <a class="btn" :href="artifactUrl(lastRun.run_id, 'scene.ply')" download="scene.ply">
        ⬇ 下载场景点云 scene.ply
      </a>
      <a class="btn" :href="artifactUrl(lastRun.run_id, 'overlay.png')" download="overlay.png">
        ⬇ 分割叠加图
      </a>
      <a class="btn" :href="artifactUrl(lastRun.run_id, 'depth_vis.png')" download="depth_vis.png">
        ⬇ 深度可视化
      </a>
    </div>

    <div v-if="runs.length" style="background:var(--panel);border:1px solid var(--bd);border-radius:10px;padding:10px">
      <b style="font-weight:500;font-size:12px">运行历史</b>
      <div v-for="r in runs.slice(0, 8)" :key="r.run_id"
           class="mini" style="display:flex;gap:12px;padding:3px 0;align-items:center">
        <span class="tabular-nums">{{ r.run_id }}</span>
        <span :style="{color: tierColor[r.device.device_effective]}">{{ tierName[r.device.device_effective] }}</span>
        <span class="tabular-nums">{{ r.device.total_ms }} ms</span>
        <span>{{ r.painting }}</span>
        <span style="margin-left:auto;opacity:.7">{{ new Date(r.ts).toLocaleString() }}</span>
      </div>
    </div>

    <div v-if="!paintings.length" class="empty">
      暂无示例画作 — 用下方命令注册一幅:
      <code class="mini">curl -F "name=示例" -F "painting=@painting.png" http://127.0.0.1:8712/api/demo/paintings</code>
    </div>
  </div>
</template>
