<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { SandboxEngine } from './sandbox/SandboxEngine.js'
import SidebarEventList from './components/SidebarEventList.vue'
import StepTimeline from './components/StepTimeline.vue'
import InfoPanel from './components/InfoPanel.vue'
import NarratorPanel from './components/NarratorPanel.vue'
import PlaybackControls from './components/PlaybackControls.vue'
import WorldModelPanel from './components/WorldModelPanel.vue'
import { fetchEvents, fetchEvent, simulate } from './api.js'

const events = ref([])
const currentEvent = ref(null)
const currentStepId = ref(1)
const playing = ref(false)
const loadingEvents = ref(true)
const error = ref('')

// ---- world-model interaction state ----
const wmActive = ref(false)            // panel open?
const wmMode = ref('')                  // '' | move/attack/alliance/retreat/hypothetical
const wmSelectedActor = ref('')
const wmBusy = ref(false)
const hypStep = ref(null)               // simulated step shown on the board

const sandboxEl = ref(null)
let engine = null
let playTimer = null

const currentStep = computed(() =>
  hypStep.value
    ? hypStep.value
    : currentEvent.value?.steps?.find((s) => s.id === currentStepId.value) || null,
)

// ---- world-model handlers ----
function enterWorldModel() {
  wmMode.value = ''
  wmSelectedActor.value = ''
  hypStep.value = null
  engine?.setPicking(true, { onPickActor, onPickGround })
}

function exitWorldModel() {
  wmMode.value = ''
  wmSelectedActor.value = ''
  hypStep.value = null
  engine?.setPicking(false)
  engine?.setSelected(null)
  const step = currentEvent.value?.steps?.find((s) => s.id === currentStepId.value)
  if (step) engine?.applyStep(step)
}

function onPickActor(id) {
  if (!id) return
  wmSelectedActor.value = id
  engine?.setSelected(id)
}

function onPickGround(lonLat) {
  if (wmMode.value !== 'move' || !wmSelectedActor.value || !currentEvent.value) return
  runSimulation({ command: 'move', actor_id: wmSelectedActor.value, target_position: lonLat })
}

async function runSimulation(cmd) {
  if (!currentEvent.value) return
  wmBusy.value = true
  error.value = ''
  try {
    const step = await simulate(currentEvent.value.id, currentStepId.value, cmd)
    hypStep.value = step
    engine?.applyStep(step)
  } catch (e) {
    // 409 carries a structured {reason, message} detail with a friendly hint;
    // FastAPI wraps it as {"detail": {...}}, so look there first
    const m = /\{.*\}/s.exec(e.message)?.[0]
    try {
      const parsed = JSON.parse(m)
      error.value = parsed?.detail?.message || parsed?.message || `世界模型推演失败：${e.message}`
    } catch {
      error.value = `世界模型推演失败：${e.message}`
    }
  } finally {
    wmBusy.value = false
  }
}

function wmSubmit(question, mode = null) {
  const m = mode || wmMode.value
  if (m === 'hypothetical') {
    if (!question?.trim()) return
    runSimulation({ command: 'hypothetical', question })
  } else if (m === 'attack' || m === 'retreat') {
    if (!wmSelectedActor.value) return
    runSimulation({ command: m, actor_id: wmSelectedActor.value })
  } else if (m === 'alliance') {
    if (!wmSelectedActor.value) return
    runSimulation({ command: 'alliance', target_nation: wmSelectedActor.value })
  }
}

function goToStep(id, { keepPlaying = true } = {}) {
  const steps = currentEvent.value?.steps || []
  const step = steps.find((s) => s.id === id)
  if (!step) return
  currentStepId.value = id
  hypStep.value = null              // leaving the hypothetical branch
  engine?.setSelected(null)
  engine?.applyStep(step)
  if (!keepPlaying) playing.value = false
}

function startPlayback() {
  playing.value = true
  scheduleNext()
}

function scheduleNext() {
  clearTimeout(playTimer)
  playTimer = setTimeout(() => {
    const steps = currentEvent.value?.steps || []
    const next = steps.find((s) => s.id === currentStepId.value + 1)
    if (next) {
      goToStep(next.id)
      scheduleNext()
    } else {
      playing.value = false
    }
  }, 9000)
}

function togglePlay() {
  if (playing.value) {
    playing.value = false
    clearTimeout(playTimer)
  } else if (currentEvent.value) {
    // resume from start if at the last step
    const steps = currentEvent.value.steps
    if (currentStepId.value >= steps[steps.length - 1].id) goToStep(1)
    startPlayback()
  }
}

function restart() {
  playing.value = false
  clearTimeout(playTimer)
  goToStep(1)
}

async function selectEvent(id) {
  playing.value = false
  clearTimeout(playTimer)
  error.value = ''
  exitWorldModel()
  try {
    currentEvent.value = await fetchEvent(id)
    currentStepId.value = 1
    engine?.setScenario(currentEvent.value)
    // wait for initial camera framing, then drop the first pieces
    setTimeout(() => goToStep(1), 300)
  } catch (e) {
    error.value = `加载剧本失败：${e.message}`
  }
}

onMounted(async () => {
  engine = new SandboxEngine(sandboxEl.value)
  try {
    events.value = await fetchEvents()
    if (events.value.length) await selectEvent(events.value[0].id)
  } catch (e) {
    error.value = `无法连接后端（${e.message}）。请先运行: cd backend && python run.py`
  } finally {
    loadingEvents.value = false
  }
})

onBeforeUnmount(() => {
  clearTimeout(playTimer)
  engine?.dispose()
})

// 暂停时镜头缓慢自动环视，播放时停止
watch(playing, (v) => { engine && (engine.rig.autoRotate = !v) })
</script>

<template>
  <div class="app">
    <div ref="sandboxEl" class="sandbox" />

    <SidebarEventList
      :events="events"
      :current-id="currentEvent?.id"
      :loading="loadingEvents"
      @select="selectEvent"
    />

    <InfoPanel :event="currentEvent" :step="currentStep">
      <template #badge>
        <span v-if="hypStep" class="hyp-badge">✦ 假想推演 · 非史实</span>
      </template>
    </InfoPanel>

    <NarratorPanel
      v-if="currentEvent"
      :event-id="currentEvent.id"
      :step-id="currentStepId"
    />

    <PlaybackControls :playing="playing" @toggle="togglePlay" />

    <button v-if="currentEvent && !wmActive" class="wm-entry panel" @click="wmActive = true" title="世界模型交互推演">
      🧠 交互推演
    </button>
    <WorldModelPanel
      v-if="wmActive && currentEvent"
      :event="currentEvent"
      :step="currentStep"
      :mode="wmMode"
      :selected-actor-id="wmSelectedActor"
      :busy="wmBusy"
      @set-mode="(m) => { wmMode = m; wmSelectedActor = ''; engine?.setSelected(null); hypStep = null }"
      @select-actor="onPickActor"
      @cancel="() => { wmMode = ''; wmSelectedActor = ''; engine?.setSelected(null) }"
      @submit-hypothetical="(q, mode) => wmSubmit(q, mode)"
      @exit="() => { wmActive = false; exitWorldModel() }"
    />

    <StepTimeline
      v-if="currentEvent"
      :steps="currentEvent.steps"
      :current="currentStepId"
      :playing="playing"
      @select="(id) => { goToStep(id); if (playing) scheduleNext(); }"
      @toggle-play="togglePlay"
      @prev="() => { goToStep(Math.max(1, currentStepId - 1)); if (playing) scheduleNext(); }"
      @next="() => { const s = currentEvent.steps.find(x => x.id === currentStepId + 1); if (s) { goToStep(s.id); if (playing) scheduleNext(); } }"
      @restart="restart"
    />

    <div v-if="error" class="error-toast panel">{{ error }}</div>

    <div class="legend panel" v-if="currentEvent">
      <b>操作</b>
      <span>🖱 拖拽旋转 · 滚轮缩放</span>
      <span class="divider" />
      <b>精神内核</b>
      <span class="spirit">{{ currentEvent.spirit_core }}</span>
    </div>
  </div>
</template>

<style scoped>
.app { width: 100%; height: 100%; position: relative; }
.sandbox { position: absolute; inset: 0; left: 300px; width: calc(100% - 300px); height: 100%; }
.error-toast {
  position: absolute;
  top: 70px; left: 50%;
  transform: translateX(-50%);
  padding: 10px 20px;
  color: #ffb4a8;
  font-size: 13px;
  border-color: rgba(231, 76, 60, 0.5);
  max-width: 640px;
}
.legend {
  position: absolute;
  bottom: 130px; right: 18px;
  width: 340px;
  padding: 10px 14px;
  font-size: 11px;
  color: var(--text-dim);
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.legend b { color: var(--accent); font-size: 11px; }
.legend .divider { width: 1px; height: 12px; background: var(--border); }
.legend .spirit { color: var(--text); }

.wm-entry {
  position: absolute;
  top: 18px;
  left: 50%;
  transform: translateX(-50%);
  padding: 9px 20px;
  color: var(--text);
  font-size: 13px;
  border: 1px solid var(--border);
  background: rgba(16, 22, 44, 0.9);
}
.wm-entry:hover { border-color: var(--accent); color: var(--accent); }

.hyp-badge {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 10px;
  background: rgba(241, 196, 15, 0.15);
  color: var(--accent);
  font-size: 11px;
  margin-bottom: 6px;
}
</style>
