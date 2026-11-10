<script setup>
// 3D 生成管理 (§4.3): TripoSplat 任务卡片流 + 批量生成 + PLY 下载
import { ref, computed, onMounted } from 'vue'
import { api, waitTask } from '../api.js'
import { t } from '../i18n.js'

const props = defineProps({ project: Object })
const emit = defineEmits(['notify', 'notify-error', 'refresh'])

const objects = ref([])
const running = ref(false)
const progress = ref(0)
const taskLog = ref([])
let runningTaskId = null

async function load() {
  try { objects.value = await api.listObjects(props.project.project_id) }
  catch (e) { emit('notify-error', e) }
}

const active = computed(() => objects.value.filter(o => !o.rejected))
const pending = computed(() => active.value.filter(o => o.gs_version === 0))
const isStale = (o) => o.gs_source_ply && !o.gs_source_ply.includes(`.v${o.gs_version}.ply`)

async function cancelRun() {
  if (!runningTaskId) return
  try { await api.cancelTask(runningTaskId) } catch (e) { emit('notify-error', e) }
}

async function runGs(oids) {
  running.value = true; progress.value = 0; taskLog.value = []
  try {
    const { task_id } = await api.runGs(props.project.project_id, oids)
    runningTaskId = task_id
    const tk = await waitTask(task_id, x => {
      progress.value = x.progress
      taskLog.value = x.log.slice(-6)
    })
    if (tk.status === 'done') {
      emit('notify', t('gsDone', tk.result.generated), 'ok')
      await load(); emit('refresh')
    } else emit('notify', t('gsFailed', tk.error || tk.status), 'err')
  } catch (e) { emit('notify-error', e) }
  finally { running.value = false; runningTaskId = null }
}

function status(o) {
  if (o.rejected) return { cls: '', t: t('stRejected') }
  if (o.gs_version === 0) return { cls: 'warn', t: t('stPending') }
  if (isStale(o)) return { cls: 'warn', t: t('stStale') }
  return { cls: 'ok', t: `v${o.gs_version}` }
}

onMounted(load)
</script>

<template>
  <div style="flex:1;display:flex;min-width:0">
    <div style="flex:1;overflow:auto;padding:14px;display:flex;flex-direction:column;gap:12px">
      <div style="display:flex;align-items:center;gap:10px">
        <b style="font-weight:600">{{ t('gsTitle') }}</b>
        <span class="mini">{{ t('activeObjects', active.length) }} · {{ t('pendingObjects', pending.length) }}</span>
        <div style="margin-left:auto;display:flex;gap:8px;align-items:center">
          <div v-if="running" style="width:160px">
            <div class="mini" style="display:flex;justify-content:space-between">
              <span>{{ t('queue') }}</span><span>{{ Math.round(progress*100) }}%</span></div>
            <div class="pbar"><i :style="{width: progress*100+'%'}"></i></div>
          </div>
          <button class="btn pri" :disabled="running || !pending.length"
                  @click="runGs([])">{{ t('batchGenerate', pending.length) }}</button>
          <button v-if="running" class="btn" style="color:var(--red)" @click="cancelRun">
            {{ t('cancelTask') }}
          </button>
        </div>
      </div>
      <div v-if="running && taskLog.length" class="mini" style="background:var(--panel);border-radius:8px;padding:8px 10px">
        <div v-for="(l, i) in taskLog" :key="i" style="padding:1px 0">▸ {{ l }}</div>
      </div>

      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(168px,1fr));gap:10px">
        <div v-for="o in objects" :key="o.object_id"
             :style="{ background:'var(--panel2)', border:'1px solid var(--bd)', borderRadius:'10px', padding:'10px',
                       display:'flex', flexDirection:'column', gap:'6px', opacity: o.rejected ? .4 : 1 }">
          <div style="height:74px;border-radius:7px;background:#0b0d12;display:flex;align-items:center;justify-content:center;overflow:hidden">
            <img v-if="!o.rejected" :src="api.maskUrl(project.project_id, o.object_id)"
                 style="max-height:100%;max-width:100%;object-fit:contain;filter:invert(1) hue-rotate(180deg)" alt="object" />
          </div>
          <div style="display:flex;justify-content:space-between;align-items:center;gap:4px">
            <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px">{{ o.label }} #{{ o.object_id }}</span>
            <span class="badge" :class="status(o).cls">{{ status(o).t }}</span>
          </div>
          <div class="mini">{{ o.rejected ? t('stSkipped') : `mask v${o.mask_version}${o.gs_version ? ' · gs v'+o.gs_version : ''}` }}</div>
          <div v-if="!o.rejected" style="display:flex;gap:6px">
            <a v-if="o.gs_version" class="btn mini" style="height:22px;padding:0 7px"
               :href="api.plyUrl(project.project_id, o.object_id)" :download="`obj${o.object_id}.ply`">PLY</a>
            <button v-if="o.gs_version && isStale(o)" class="btn mini" style="height:22px;padding:0 7px;color:var(--yel)"
                    :disabled="running" @click="runGs([o.object_id])">{{ t('rerunPlain') }}</button>
            <button v-else-if="o.gs_version" class="btn mini" style="height:22px;padding:0 7px"
                    :disabled="running" @click="runGs([o.object_id])">{{ t('rerun', o.gs_version+1) }}</button>
            <button v-else class="btn mini" style="height:22px;padding:0 7px;color:var(--acc)"
                    :disabled="running" @click="runGs([o.object_id])">{{ t('generate') }}</button>
          </div>
        </div>
      </div>
      <div v-if="!objects.length" class="empty">{{ t('gsEmpty') }}</div>
    </div>
  </div>
</template>
