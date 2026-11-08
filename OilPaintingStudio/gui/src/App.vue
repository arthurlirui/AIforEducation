<script setup>
// PaintingStudio 六步工作台 (设计文档 §4) + 论文 Demo (§6)
import { ref, computed, onMounted } from 'vue'
import { api } from './api.js'
import { t, lang, setLang } from './i18n.js'
import ProjectHome from './components/ProjectHome.vue'
import SegmentView from './components/SegmentView.vue'
import GsView from './components/GsView.vue'
import SceneView from './components/SceneView.vue'
import KeyframeView from './components/KeyframeView.vue'
import ComposeView from './components/ComposeView.vue'
import DemoView from './components/DemoView.vue'

const project = ref(null)          // 当前项目 (GET /api/projects/{id})
const step = ref(1)                // 1..6
const toast = ref(null)            // {text, kind}
let toastTimer = null

function notify(text, kind = '') {
  toast.value = { text, kind }
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = null }, 2600)
}
function notifyError(e) { notify(e.message || String(e), 'err') }

const steps = computed(() => {
  const noProject = !project.value
  const ps = project.value?.pipeline_state || {}
  const seg = ps.segment?.status
  const gs = ps.gs?.status
  const lock = (v) => noProject ? 'locked' : v
  return [
    { n: 1, t: t('step1'), s: lock(seg || 'todo'), d: 'PaintParse' },
    { n: 2, t: t('step2'), s: lock(seg === 'done' ? (gs || 'todo') : 'locked'), d: 'TripoSplat' },
    { n: 3, t: t('step3'), s: lock(gs === 'done' ? 'part' : 'locked'), d: 'scene.json' },
    { n: 4, t: t('step4'), s: lock('todo'), d: 'SketchComp' },
    { n: 5, t: t('step5'), s: lock('todo'), d: 'ArtiFlow' },
    { n: 6, t: t('step6'), s: 'done', d: 'GPU/CPU/MOCK' },
  ]
})

function openProject(p) { project.value = p; step.value = 1 }
async function refreshProject() {
  if (!project.value) return
  try { project.value = await api.getProject(project.value.project_id) }
  catch { /* 项目可能已删除 */ }
}

async function doUndo() {
  if (!project.value) return
  try {
    await api.undo(project.value.project_id)
    notify(t('undo'), 'ok')
    await refreshProject()
  } catch (e) { notifyError(e) }
}
async function doRedo() {
  if (!project.value) return
  try {
    await api.redo(project.value.project_id)
    notify(t('redo'), 'ok')
  } catch (e) { notifyError(e) }
}

onMounted(async () => {
  try {
    const list = await api.listProjects()
    if (list.length) openProject(list[0])
  } catch (e) { notifyError(e) }
})
</script>

<template>
  <div style="height:100%;display:flex;flex-direction:column">
    <!-- 顶栏 -->
    <header style="height:48px;background:var(--panel);border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:12px;padding:0 14px;flex:none">
      <div style="display:flex;align-items:center;gap:8px;font-weight:600;font-size:14px">
        <span style="width:22px;height:22px;border-radius:6px;background:linear-gradient(135deg,var(--acc),var(--pur));display:flex;align-items:center;justify-content:center;color:#fff;font-size:12px">P</span>
        PaintingStudio
      </div>
      <template v-if="project">
        <span class="mini">{{ project.name }}</span>
        <span class="badge ok">{{ t('connected') }}</span>
      </template>
      <div style="margin-left:auto;display:flex;gap:8px;align-items:center">
        <!-- 语言设置 -->
        <select :value="lang" @change="setLang($event.target.value)"
                :aria-label="t('langLabel')" :title="t('langLabel')"
                style="padding:4px 6px;height:28px">
          <option value="zh">中文</option>
          <option value="en">English</option>
        </select>
        <button v-if="project" class="btn" @click="doUndo">{{ t('undo') }}</button>
        <button v-if="project" class="btn" @click="doRedo">{{ t('redo') }}</button>
        <button v-if="project" class="btn" @click="refreshProject">{{ t('refresh') }}</button>
        <button v-if="project" class="btn danger" @click="project=null">{{ t('closeProject') }}</button>
      </div>
    </header>

    <div style="flex:1;display:flex;min-height:0">
      <!-- 左侧管线步骤栏 (§4 状态机) -->
      <nav style="width:180px;background:var(--panel);border-right:1px solid var(--bd);padding:10px 8px;display:flex;flex-direction:column;gap:4px;flex:none">
        <button v-for="s in steps" :key="s.n"
          :style="{ display:'flex', alignItems:'center', gap:'10px', padding:'10px', borderRadius:'8px', width:'100%', textAlign:'left',
            color: s.n===step ? 'var(--tx)' : 'var(--dim)',
            background: s.n===step ? 'var(--panel2)' : 'transparent',
            opacity: s.s==='locked' ? .45 : 1 }"
          @click="s.s!=='locked' && (step=s.n)">
          <span :style="{ width:'22px', height:'22px', borderRadius:'50%', flex:'none', display:'flex', alignItems:'center', justifyContent:'center', fontSize:'11px',
            background: s.s==='done' ? 'rgba(63,191,127,.18)' : (s.n===step ? 'var(--acc)' : 'var(--panel2)'),
            color: s.s==='done' ? 'var(--grn)' : (s.n===step ? '#fff' : 'var(--dim)') }">{{ s.n }}</span>
          <span>
            {{ s.t }}
            <small class="mini" style="display:block">{{ s.s==='locked' ? t('stepLocked') : s.d }}</small>
          </span>
        </button>
      </nav>

      <!-- 工作区 -->
      <main style="flex:1;display:flex;min-width:0;min-height:0">
        <DemoView v-if="step===6" />
        <ProjectHome v-else-if="!project" @open="openProject" @notify="notify" @notify-error="notifyError" />
        <SegmentView v-else-if="step===1" :project="project" @notify="notify" @notify-error="notifyError" @refresh="refreshProject" />
        <GsView v-else-if="step===2" :project="project" @notify="notify" @notify-error="notifyError" @refresh="refreshProject" />
        <SceneView v-else-if="step===3" :project="project" @notify="notify" @notify-error="notifyError" @refresh="refreshProject" />
        <KeyframeView v-else-if="step===4" :project="project" @notify="notify" @notify-error="notifyError" @refresh="refreshProject" />
        <ComposeView v-else :project="project" @notify="notify" @notify-error="notifyError" @refresh="refreshProject" />
      </main>
    </div>

    <!-- 底部状态栏 -->
    <footer style="height:26px;background:var(--panel);border-top:1px solid var(--bd);display:flex;align-items:center;gap:16px;padding:0 14px;flex:none" class="mini">
      <span v-if="project">{{ t('footerProject') }}: {{ project.name }} · project.json</span>
      <span>undo: {{ project?.undo_depth ?? 0 }} / 50</span>
      <span style="margin-left:auto">{{ t('footerTagline') }}</span>
    </footer>

    <div v-if="toast" class="toast" :class="toast.kind"><span class="st"></span>{{ toast.text }}</div>
  </div>
</template>
