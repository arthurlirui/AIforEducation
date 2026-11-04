<script setup>
// 项目主页: 画作库 + 导入 (§4.1)
import { ref, onMounted } from 'vue'
import { api } from '../api.js'

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
  if (!name.value || !file.value) { emit('notify', '请填写名称并选择画作图片'); return }
  creating.value = true
  try {
    const p = await api.createProject(name.value, file.value)
    emit('notify', `项目已创建: ${p.name}`, 'ok')
    name.value = ''; file.value = null
    await load()
    emit('open', p)
  } catch (e) { emit('notify-error', e) }
  finally { creating.value = false }
}

async function remove(p) {
  if (!confirm(`删除项目「${p.name}」? (移入回收站, 可手动恢复)`)) return
  try {
    await api.deleteProject(p.project_id)
    emit('notify', '已移入回收站', 'ok')
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
      <h3 style="font-weight:600;margin-bottom:12px">画作库</h3>
      <div v-if="!projects.length" class="empty" style="padding:20px">
        暂无项目 — 在右侧导入一幅画作开始
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px">
        <div v-for="p in projects" :key="p.project_id"
             style="background:var(--panel);border:1px solid var(--bd);border-radius:10px;overflow:hidden;cursor:pointer"
             @click="emit('open', p)">
          <img :src="api.paintingUrl(p.project_id, true)" style="width:100%;height:110px;object-fit:cover" alt="画作缩略图" />
          <div style="padding:8px 10px">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:6px">
              <b style="font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ p.name }}</b>
              <button class="mini" style="color:var(--red);flex:none" @click.stop="remove(p)">删除</button>
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
      <h3 style="font-weight:600">导入画作</h3>
      <label class="mini">项目名称</label>
      <input v-model="name" placeholder="如: 星月夜" />
      <label class="mini">画作图片 (PNG/JPG)</label>
      <input type="file" accept="image/png,image/jpeg" @change="file = $event.target.files[0]" />
      <img v-if="file" :src="URL.createObjectURL(file)" style="width:100%;border-radius:8px" alt="预览" />
      <button class="btn pri" :disabled="creating" @click="create">
        {{ creating ? '创建中…' : '创建项目' }}
      </button>
      <div class="mini">
        创建后生成标准项目目录 (source/ stage1/…stage5/)，
        project.json 与 CLI 产物互通。
      </div>
    </aside>
  </div>
</template>
