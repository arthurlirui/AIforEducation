<script setup>
// 项目主页: 画作库 + 导入 (§4.1)
import { ref, onMounted } from 'vue'
import { api } from '../api.js'
import { t } from '../i18n.js'

const emit = defineEmits(['open', 'notify', 'notify-error'])
const projects = ref([])
const name = ref('')
const file = ref(null)
const creating = ref(false)

async function load() {
  try { projects.value = await api.listProjects() }
  catch (e) { emit('notify-error', e) }
}

async function create() {
  if (!name.value || !file.value) { emit('notify', t('projectName') + ' / ' + t('paintingFile')); return }
  creating.value = true
  try {
    const p = await api.createProject(name.value, file.value)
    emit('notify', `${t('createProject')}: ${p.name}`, 'ok')
    name.value = ''; file.value = null
    await load()
    emit('open', p)
  } catch (e) { emit('notify-error', e) }
  finally { creating.value = false }
}

async function remove(p) {
  if (!confirm(t('deleteConfirm', p.name))) return
  try {
    await api.deleteProject(p.project_id)
    emit('notify', t('trashedToast'), 'ok')
    await load()
  } catch (e) { emit('notify-error', e) }
}

function statusDot(st) {
  return { done: 'var(--grn)', partial: 'var(--yel)', part: 'var(--yel)',
           running: 'var(--acc)', failed: 'var(--red)', todo: '#3a4356' }[st?.status] || '#3a4356'
}

onMounted(load)
</script>

<template>
  <div style="flex:1;display:flex;min-width:0">
    <!-- 画作库 -->
    <div style="flex:1;overflow:auto;padding:16px">
      <h3 style="font-weight:600;margin-bottom:12px">{{ t('library') }}</h3>
      <div v-if="!projects.length" class="empty" style="padding:20px">
        {{ t('libraryEmpty') }}
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px">
        <div v-for="p in projects" :key="p.project_id"
             style="background:var(--panel);border:1px solid var(--bd);border-radius:10px;overflow:hidden;cursor:pointer"
             @click="emit('open', p)">
          <img :src="api.paintingUrl(p.project_id, true)" style="width:100%;height:110px;object-fit:cover" alt="thumbnail" />
          <div style="padding:8px 10px">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:6px">
              <b style="font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ p.name }}</b>
              <button class="mini" style="color:var(--red);flex:none" @click.stop="remove(p)">{{ t('deleteBtn') }}</button>
            </div>
            <div style="display:flex;gap:5px;margin-top:6px">
              <span v-for="(st, k) in p.pipeline_state" :key="k"
                    :style="{width:'14px',height:'6px',borderRadius:'3px',background:statusDot(st)}"
                    :title="`${k}: ${st.status}`"></span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 导入面板 -->
    <aside style="width:280px;background:var(--panel);border-left:1px solid var(--bd);padding:16px;display:flex;flex-direction:column;gap:10px;flex:none;overflow:auto">
      <h3 style="font-weight:600">{{ t('importTitle') }}</h3>
      <label class="mini">{{ t('projectName') }}</label>
      <input v-model="name" :placeholder="t('projectNamePh')" />
      <label class="mini">{{ t('paintingFile') }}</label>
      <input type="file" accept="image/png,image/jpeg" @change="file = $event.target.files[0]" />
      <img v-if="file" :src="URL.createObjectURL(file)" style="width:100%;border-radius:8px" alt="preview" />
      <button class="btn pri" :disabled="creating" @click="create">
        {{ creating ? t('creating') : t('createProject') }}
      </button>
      <div class="mini">{{ t('importHint') }}</div>
    </aside>
  </div>
</template>
