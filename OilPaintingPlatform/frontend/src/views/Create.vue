<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useStore } from '../stores/app'
import { generateImage } from '../api'
import StyleCard from '../components/StyleCard.vue'

const store = useStore()

const prompt = ref('')
const selectedStyle = ref(null)
const provider = ref('mock')
const size = ref('1024x1024')
const extraKeywords = ref('')
const loading = ref(false)
const error = ref('')
const result = ref(null)

// ---- Collapsible style list ----
const styleExpanded = ref(false)
const styleSearch = ref('')

const filteredStyles = computed(() => {
  if (!styleSearch.value.trim()) return store.styles
  const q = styleSearch.value.toLowerCase()
  return store.styles.filter(
    (s) =>
      s.name.toLowerCase().includes(q) ||
      s.name_en.toLowerCase().includes(q) ||
      s.id.toLowerCase().includes(q)
  )
})

const selectedStyleObj = computed(() =>
  store.styles.find((s) => s.id === selectedStyle.value)
)

function selectStyle(id) {
  selectedStyle.value = id
  styleExpanded.value = false
}

function toggleStyleList() {
  styleExpanded.value = !styleExpanded.value
}

// ---- Collapsible provider selector + settings ----
const providerExpanded = ref(false)
const providerSettings = ref({})  // { [providerId]: { api_key, api_id, base_url } }

// Load saved credentials from localStorage
function loadCredentials() {
  try {
    const saved = JSON.parse(localStorage.getItem('provider_credentials') || '{}')
    providerSettings.value = saved
  } catch {
    providerSettings.value = {}
  }
}

// Save credentials to localStorage
function saveCredentials() {
  localStorage.setItem('provider_credentials', JSON.stringify(providerSettings.value))
}

function toggleProviderList() {
  providerExpanded.value = !providerExpanded.value
}

function selectProvider(id) {
  provider.value = id
  providerExpanded.value = false
}

function getProviderInfo(id) {
  return store.providers.find((p) => p.id === id)
}

function ensureSettingsEntry(id) {
  if (!providerSettings.value[id]) {
    providerSettings.value[id] = { api_key: '', api_id: '', base_url: '' }
  }
}

const selectedProviderInfo = computed(() => getProviderInfo(provider.value))
const selectedProviderName = computed(() => selectedProviderInfo.value?.name || provider.value)

// ---- Prompt library ----
const promptCategories = computed(() => {
  const set = new Set(store.prompts.map((p) => p.category))
  return ['全部', ...set]
})
const promptFilter = ref('全部')
const filteredPrompts = computed(() => {
  if (promptFilter.value === '全部') return store.prompts
  return store.prompts.filter((p) => p.category === promptFilter.value)
})

function usePromptTemplate(tpl) {
  prompt.value = tpl.prompt
  if (tpl.recommended_style) {
    selectedStyle.value = tpl.recommended_style
  }
}

// ---- Composed prompt preview ----
const composedPreview = computed(() => {
  if (!selectedStyle.value || !prompt.value) return ''
  const style = store.styles.find((s) => s.id === selectedStyle.value)
  if (!style) return ''
  const parts = [prompt.value.trim(), ...style.prompt_keywords]
  if (extraKeywords.value) parts.push(extraKeywords.value.trim())
  return parts.join(', ')
})

// ---- Download ----
function downloadImage(url, filename) {
  const link = document.createElement('a')
  link.href = url
  link.download = filename || 'oil-painting.png'
  link.target = '_blank'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
}

function getFilename(img, index) {
  const styleName = result.value?.style?.name || 'painting'
  const ts = Date.now()
  const ext = img.url.split('.').pop().split('?')[0] || 'png'
  return `oilpainting-${styleName}-${ts}-${index + 1}.${ext}`
}

// ---- Generate ----
async function handleGenerate() {
  if (!prompt.value.trim()) {
    error.value = '请输入提示词'
    return
  }
  if (!selectedStyle.value) {
    error.value = '请选择一种艺术风格'
    return
  }
  error.value = ''
  loading.value = true
  result.value = null
  try {
    // Build credentials from localStorage settings
    const creds = providerSettings.value[provider.value] || null
    const payload = {
      prompt: prompt.value,
      style_id: selectedStyle.value,
      provider: provider.value || null,
      size: size.value,
      n: 1,
      extra_keywords: extraKeywords.value || null,
      credentials: creds && (creds.api_key || creds.api_id || creds.base_url)
        ? creds
        : null,
    }
    result.value = await generateImage(payload)
  } catch (e) {
    error.value = e?.response?.data?.detail || e.message || '生成失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

const sizes = ['1024x1024', '1024x1792', '1792x1024', '768x768', '512x512']

onMounted(() => {
  store.bootstrap()
  loadCredentials()
})
</script>

<template>
  <div class="container">
    <h1 class="section-title">AI 油画创作</h1>
    <p class="section-sub">输入提示词 → 选择风格 → 配置模型 → 生成油画</p>

    <div class="grid" style="grid-template-columns: 1fr 1fr; gap:32px; align-items:start;">
      <!-- Left: form -->
      <div>
        <!-- Step 1: prompt -->
        <div class="card" style="margin-bottom:20px;">
          <label>1️⃣ 输入提示词</label>
          <textarea
            v-model="prompt"
            rows="4"
            placeholder="例如：一位穿白衣的少女坐在窗边读书，侧光从右侧窗户洒入，温暖的金色光线"
            style="margin-top:8px;"
          ></textarea>
          <div style="margin-top:10px;">
            <label>附加关键词（可选）</label>
            <input
              v-model="extraKeywords"
              placeholder="如：thick impasto, golden hour"
              style="margin-top:6px;"
            />
          </div>
        </div>

        <!-- Step 2: style (collapsible) -->
        <div class="card" style="margin-bottom:20px;">
          <div
            style="display:flex; align-items:center; justify-content:space-between; cursor:pointer; user-select:none;"
            @click="toggleStyleList"
          >
            <label style="margin:0; cursor:pointer;">2️⃣ 选择艺术风格</label>
            <span style="font-size:13px; color:var(--text-light);">
              {{ selectedStyleObj ? selectedStyleObj.name : '未选择' }}
              <span style="margin-left:8px; font-size:16px;">{{ styleExpanded ? '▾' : '▸' }}</span>
            </span>
          </div>

          <div v-if="selectedStyleObj && !styleExpanded" style="margin-top:10px; padding:10px 14px; background:#fdf6ee; border-radius:8px; display:flex; align-items:center; justify-content:space-between;">
            <div>
              <strong style="color:var(--primary-dark);">{{ selectedStyleObj.name }}</strong>
              <span style="color:var(--text-light); font-size:13px; margin-left:8px;">{{ selectedStyleObj.name_en }} · {{ selectedStyleObj.era }}</span>
            </div>
            <button class="btn btn-outline" style="padding:4px 12px; font-size:13px;" @click.stop="styleExpanded = true">更换</button>
          </div>

          <div v-if="styleExpanded">
            <input v-model="styleSearch" placeholder="搜索风格名称…"  style="margin-top:12px;" />
            <div style="margin-top:12px; max-height:420px; overflow-y:auto;">
              <div
                v-for="s in filteredStyles"
                :key="s.id"
                class="style-list-item"
                :class="{ 'style-list-item-selected': selectedStyle === s.id }"
                @click="selectStyle(s.id)"
              >
                <div style="display:flex; justify-content:space-between; align-items:start;">
                  <div>
                    <strong style="color:var(--primary-dark); font-size:15px;">{{ s.name }}</strong>
                    <span style="color:var(--text-light); font-size:13px; margin-left:8px;">{{ s.name_en }}</span>
                  </div>
                  <span class="badge">{{ s.era }}</span>
                </div>
                <p style="font-size:13px; color:var(--text-light); margin-top:4px;">{{ s.description }}</p>
                <p v-if="s.reference_artists && s.reference_artists.length" style="font-size:12px; color:var(--text-light); margin-top:4px;">
                  代表艺术家：{{ s.reference_artists.join(' · ') }}
                </p>
              </div>
              <div v-if="filteredStyles.length === 0" style="text-align:center; padding:20px; color:var(--text-light);">
                未找到匹配的风格
              </div>
            </div>
            <button class="btn btn-outline" style="margin-top:10px; padding:6px 16px; font-size:13px; width:100%;" @click="styleExpanded = false">收起列表</button>
          </div>
        </div>

        <!-- Step 3: provider (collapsible + settings) -->
        <div class="card" style="margin-bottom:20px;">
          <div
            style="display:flex; align-items:center; justify-content:space-between; cursor:pointer; user-select:none;"
            @click="toggleProviderList"
          >
            <label style="margin:0; cursor:pointer;">3️⃣ 选择生图模型</label>
            <span style="font-size:13px; color:var(--text-light);">
              {{ selectedProviderName }}
              <span v-if="selectedProviderInfo?.free" class="badge badge-accent" style="margin-left:6px;">免费</span>
              <span style="margin-left:8px; font-size:16px;">{{ providerExpanded ? '▾' : '▸' }}</span>
            </span>
          </div>

          <!-- Collapsed summary -->
          <div v-if="!providerExpanded" style="margin-top:10px; padding:10px 14px; background:#f5f0e8; border-radius:8px; display:flex; align-items:center; justify-content:space-between;">
            <div>
              <strong style="color:var(--primary-dark);">{{ selectedProviderName }}</strong>
              <p v-if="selectedProviderInfo" style="font-size:13px; color:var(--text-light); margin-top:2px;">{{ selectedProviderInfo.description }}</p>
            </div>
            <button class="btn btn-outline" style="padding:4px 12px; font-size:13px;" @click.stop="providerExpanded = true">更换 / 设置</button>
          </div>

          <!-- Expanded: provider list + settings -->
          <div v-if="providerExpanded">
            <!-- Provider list -->
            <div style="margin-top:12px; max-height:260px; overflow-y:auto;">
              <div
                v-for="p in store.providers"
                :key="p.id"
                class="style-list-item"
                :class="{ 'style-list-item-selected': provider === p.id }"
                @click="selectProvider(p.id)"
              >
                <div style="display:flex; justify-content:space-between; align-items:start;">
                  <div>
                    <strong style="color:var(--primary-dark); font-size:15px;">{{ p.name }}</strong>
                    <span v-if="p.free" class="badge badge-accent" style="margin-left:8px;">免费</span>
                    <span v-if="p.needs_api_key" class="badge" style="margin-left:4px;">需 Key</span>
                  </div>
                </div>
                <p style="font-size:13px; color:var(--text-light); margin-top:4px;">{{ p.description }}</p>
              </div>
            </div>

            <!-- Settings for selected provider -->
            <div v-if="selectedProviderInfo" style="margin-top:16px; padding-top:16px; border-top:1px solid var(--border);">
              <label style="font-size:14px; font-weight:700;">⚙️ {{ selectedProviderInfo.name }} 设置</label>

              <div v-if="!selectedProviderInfo.needs_api_key && !selectedProviderInfo.needs_api_id && !selectedProviderInfo.needs_base_url" style="margin-top:10px; padding:10px 14px; background:#e8f5e9; border-radius:8px; font-size:13px; color:#2e7d32;">
                ✓ 此模型无需任何配置，可直接使用
              </div>

              <div v-else style="margin-top:10px;">
                <div v-if="selectedProviderInfo.needs_api_key" style="margin-bottom:12px;">
                  <label style="font-size:13px;">API Key</label>
                  <input
                    :type="'password'"
                    :value="(providerSettings[provider] || {}).api_key || ''"
                    @input="ensureSettingsEntry(provider); providerSettings[provider].api_key = $event.target.value; saveCredentials()"
                    placeholder="粘贴你的 API Key"
                    style="margin-top:6px;"
                  />
                </div>

                <div v-if="selectedProviderInfo.needs_api_id" style="margin-bottom:12px;">
                  <label style="font-size:13px;">API ID（如需要）</label>
                  <input
                    :type="'text'"
                    :value="(providerSettings[provider] || {}).api_id || ''"
                    @input="ensureSettingsEntry(provider); providerSettings[provider].api_id = $event.target.value; saveCredentials()"
                    placeholder="API ID / App ID"
                    style="margin-top:6px;"
                  />
                </div>

                <div v-if="selectedProviderInfo.needs_base_url" style="margin-bottom:12px;">
                  <label style="font-size:13px;">Base URL</label>
                  <input
                    :type="'text'"
                    :value="(providerSettings[provider] || {}).base_url || ''"
                    @input="ensureSettingsEntry(provider); providerSettings[provider].base_url = $event.target.value; saveCredentials()"
                    :placeholder="selectedProviderInfo.default_base_url || 'https://...'"
                    style="margin-top:6px;"
                  />
                  <p v-if="selectedProviderInfo.default_base_url" style="font-size:12px; color:var(--text-light); margin-top:4px;">
                    默认: {{ selectedProviderInfo.default_base_url }}
                  </p>
                </div>

                <p style="font-size:12px; color:var(--text-light);">
                  💡 凭据保存在浏览器 localStorage 中，仅发送给后端用于本次生成，不会上传到任何第三方。
                </p>
              </div>
            </div>

            <button class="btn btn-outline" style="margin-top:10px; padding:6px 16px; font-size:13px; width:100%;" @click="providerExpanded = false">收起</button>
          </div>
        </div>

        <!-- Step 4: size -->
        <div class="card" style="margin-bottom:20px;">
          <label>4️⃣ 图像尺寸</label>
          <select v-model="size" style="margin-top:8px;">
            <option v-for="sz in sizes" :key="sz" :value="sz">{{ sz }}</option>
          </select>
        </div>

        <!-- Prompt library -->
        <div class="card" style="margin-bottom:20px;">
          <label>💡 内置提示词库（点击使用）</label>
          <div style="display:flex; gap:6px; flex-wrap:wrap; margin:10px 0 14px;">
            <button
              v-for="c in promptCategories"
              :key="c"
              class="btn"
              :class="promptFilter === c ? 'btn-primary' : 'btn-outline'"
              style="padding:4px 12px; font-size:13px;"
              @click="promptFilter = c"
            >{{ c }}</button>
          </div>
          <div class="grid grid-3">
            <div
              v-for="tpl in filteredPrompts"
              :key="tpl.id"
              class="card"
              style="padding:14px; cursor:pointer; border:2px solid transparent;"
              @click="usePromptTemplate(tpl)"
            >
              <div style="display:flex; justify-content:space-between; align-items:start;">
                <h4 style="color:var(--primary-dark); font-size:15px;">{{ tpl.title }}</h4>
                <span class="badge">{{ tpl.category }}</span>
              </div>
              <p style="font-size:13px; color:var(--text-light); margin-top:6px;">{{ tpl.description }}</p>
              <p style="font-size:12px; color:var(--text-light); margin-top:6px; word-break:break-all;">
                "{{ tpl.prompt.substring(0, 60) }}{{ tpl.prompt.length > 60 ? '…' : '' }}"
              </p>
              <p v-if="store.styles.find(s => s.id === tpl.recommended_style)" style="font-size:12px; margin-top:6px;">
                <span class="badge badge-accent">推荐: {{ store.styles.find(s => s.id === tpl.recommended_style).name }}</span>
              </p>
            </div>
          </div>
        </div>

        <!-- Composed preview -->
        <div v-if="composedPreview" class="card" style="margin-bottom:20px; background:#fdf6ee;">
          <label>📋 合成提示词预览</label>
          <p style="font-size:13px; color:var(--text); margin-top:8px; word-break:break-all;">
            {{ composedPreview }}
          </p>
        </div>

        <button class="btn btn-primary" style="width:100%; padding:14px;" :disabled="loading" @click="handleGenerate">
          {{ loading ? '正在生成…' : '🎨 生成油画' }}
        </button>
        <p v-if="error" style="color:var(--accent); margin-top:12px;">{{ error }}</p>
      </div>

      <!-- Right: result -->
      <div>
        <div class="card" style="position:sticky; top:80px;">
          <label>生成结果</label>
          <div v-if="loading" style="text-align:center;">
            <div class="spinner"></div>
            <p style="color:var(--text-light);">正在调用视觉大模型，请稍候…</p>
          </div>
          <div v-else-if="result">
            <div v-for="(img, i) in result.images" :key="i" style="margin-bottom:16px;">
              <img :src="img.url" class="gen-image" style="margin-bottom:10px;" />
              <button
                class="btn btn-outline"
                style="width:100%; padding:8px; font-size:14px;"
                @click="downloadImage(img.url, getFilename(img, i))"
              >
                ⬇ 下载图片
              </button>
            </div>
            <div style="font-size:14px;">
              <p style="margin-bottom:6px;">
                <span class="badge badge-accent">{{ result.style.name }}</span>
                <span class="badge" style="margin-left:6px;">{{ result.provider }}</span>
                <span class="badge" style="margin-left:6px;">{{ result.elapsed_ms }}ms</span>
              </p>
              <details style="margin-top:10px;">
                <summary style="cursor:pointer; color:var(--text-light);">查看完整提示词</summary>
                <p style="margin-top:8px; color:var(--text); word-break:break-all;">{{ result.composed_prompt }}</p>
              </details>
            </div>
          </div>
          <div v-else class="empty-state">
            <p>🎨</p>
            <p>填写左侧表单，点击「生成油画」开始创作</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.style-list-item {
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: all 0.2s;
}
.style-list-item:hover {
  background: #fdf6ee;
  border-color: var(--primary);
}
.style-list-item-selected {
  background: #fdf6ee;
  border-color: var(--primary);
  border-width: 2px;
}
</style>
