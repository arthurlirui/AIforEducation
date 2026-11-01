<script setup>
import { onMounted, onBeforeUnmount, ref, computed, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchMasterpiece } from '../api'
import { PaintingScene } from '../three/PaintingScene'

const route = useRoute()
const router = useRouter()
const container = ref(null)
const caption = ref(null)
const data = ref(null)
const error = ref('')
const chapterIndex = ref(0)
const playing = ref(false)
const narrationOn = ref(false)
const progress = ref(0)
let scene = null
let chapterTimer = null
let progressTimer = null
const speech = window.speechSynthesis || null

const chapter = computed(() => (data.value ? data.value.chapters[chapterIndex.value] : null))

function speak(text) {
  if (!speech || !narrationOn.value) return
  speech.cancel()
  const u = new SpeechSynthesisUtterance(text)
  u.lang = 'zh-CN'
  u.rate = 0.95
  speech.speak(u)
}

function stopSpeech() {
  if (speech) speech.cancel()
}

function applyChapter(idx) {
  const c = data.value.chapters[idx]
  chapterIndex.value = idx
  progress.value = 0
  if (scene) scene.focusLayer(c.focus)
  speak(`${c.title}。${c.text}`)
}

function startTour() {
  playing.value = true
  applyChapter(0)
}

function nextChapter() {
  if (chapterIndex.value < data.value.chapters.length - 1) {
    applyChapter(chapterIndex.value + 1)
  } else {
    stopTour()
    router.push(`/quiz/${data.value.id}`)
  }
}

function prevChapter() {
  if (chapterIndex.value > 0) applyChapter(chapterIndex.value - 1)
}

function stopTour() {
  playing.value = false
  clearInterval(chapterTimer)
  clearInterval(progressTimer)
  stopSpeech()
}

function resumeTour() {
  playing.value = true
  const dur = (chapter.value?.duration || 15) * 1000
  clearInterval(chapterTimer)
  clearInterval(progressTimer)
  chapterTimer = setInterval(nextChapter, dur)
  progressTimer = setInterval(() => {
    progress.value = Math.min(1, progress.value + 100 / dur)
  }, 100)
}

function gotoChapter(i) {
  applyChapter(i)
  resumeTour()
}

function toggleNarration() {
  narrationOn.value = !narrationOn.value
  if (narrationOn.value && chapter.value) {
    speak(`${chapter.value.title}。${chapter.value.text}`)
  } else {
    stopSpeech()
  }
}

onMounted(async () => {
  try {
    data.value = await fetchMasterpiece(route.params.id)
    await nextTick()
    scene = new PaintingScene(container.value, { layers: data.value.layers })
  } catch (e) {
    error.value = `加载失败: ${e.message}（请确认后端已启动在 8300 端口）`
  }
})

onBeforeUnmount(() => {
  stopTour()
  if (scene) scene.dispose()
})
</script>

<template>
  <div class="tour">
    <!-- 3D canvas -->
    <div ref="container" class="stage"></div>

    <!-- top bar -->
    <header class="topbar panel">
      <router-link to="/" class="back">← 目录</router-link>
      <div v-if="data" class="titles">
        <strong>{{ data.title }}</strong>
        <span>{{ data.artist }} · {{ data.year }} · {{ data.movement }}</span>
      </div>
      <button class="btn ghost small" :class="{ on: narrationOn }" @click="toggleNarration">
        {{ narrationOn ? '🔊 语音开' : '🔈 语音关' }}
      </button>
    </header>

    <div v-if="error" class="error panel">{{ error }}</div>

    <!-- entry overlay -->
    <div v-if="data && !playing && chapterIndex === 0" class="intro panel">
      <h1>{{ data.title }}</h1>
      <p class="en">{{ data.title_en }} — {{ data.artist_en }}</p>
      <p class="meta">{{ data.medium }} · {{ data.size }} · {{ data.location }}</p>
      <p class="summary">{{ data.summary }}</p>
      <button class="btn primary" @click="startTour">▶ 开始沉浸导览</button>
      <p class="hint">导览中可移动鼠标环视画面 · 共 {{ data.chapters.length }} 章</p>
    </div>

    <!-- caption + timeline -->
    <div v-if="data && playing" class="bottom">
      <div class="timeline">
        <button
          v-for="(c, i) in data.chapters"
          :key="c.id"
          class="dot"
          :class="{ active: i === chapterIndex, done: i < chapterIndex }"
          :title="c.title"
          @click="gotoChapter(i)"
        ></button>
      </div>
      <transition name="fade" mode="out-in">
        <div ref="caption" class="caption panel" :key="chapter?.id">
          <div class="cap-head">
            <span class="chip">{{ chapter?.type }}</span>
            <h2>{{ chapter?.title }}</h2>
            <em>{{ chapter?.subtitle }}</em>
          </div>
          <p>{{ chapter?.text }}</p>
          <div class="cap-foot">
            <div class="pbar"><div class="fill" :style="{ width: (progress * 100) + '%' }"></div></div>
            <span class="counter">{{ chapterIndex + 1 }} / {{ data.chapters.length }}</span>
            <div class="controls">
              <button class="btn ghost small" @click="prevChapter" :disabled="chapterIndex === 0">‹ 上一章</button>
              <button class="btn ghost small" @click="nextChapter">{{ chapterIndex === data.chapters.length - 1 ? '去测验 →' : '下一章 ›' }}</button>
              <button class="btn ghost small" @click="stopTour">⏸ 暂停</button>
            </div>
          </div>
        </div>
      </transition>
    </div>

    <!-- paused overlay -->
    <div v-if="data && !playing && chapterIndex > 0" class="paused panel">
      <p>已暂停 · 第 {{ chapterIndex + 1 }} 章：{{ chapter?.title }}</p>
      <button class="btn primary" @click="resumeTour">▶ 继续</button>
    </div>
  </div>
</template>

<style scoped>
.tour { position: fixed; inset: 0; overflow: hidden; }
.stage { position: absolute; inset: 0; cursor: crosshair; }

.topbar {
  position: absolute; top: 16px; left: 16px; right: 16px;
  display: flex; align-items: center; gap: 18px;
  padding: 10px 18px;
}
.back { color: var(--text-dim); font-size: 14px; }
.back:hover { color: var(--gold); }
.titles { display: flex; flex-direction: column; flex: 1; }
.titles strong { font-size: 17px; letter-spacing: 1px; }
.titles span { font-size: 12px; color: var(--text-dim); }
.small { padding: 6px 14px; font-size: 13px; }
.on { border-color: var(--gold); }

.error { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); padding: 24px 32px; color: #ffb4a8; }

.intro {
  position: absolute; left: 50%; top: 50%;
  transform: translate(-50%, -50%);
  max-width: 560px; padding: 36px 44px; text-align: center;
}
.intro h1 { font-size: 34px; letter-spacing: 4px; margin-bottom: 4px; }
.intro .en { color: var(--text-dim); font-style: italic; }
.intro .meta { font-size: 13px; color: var(--text-dim); margin: 10px 0; }
.intro .summary { margin: 14px 0 22px; font-size: 15px; }
.intro .hint { margin-top: 14px; font-size: 12px; color: var(--text-dim); }

.bottom { position: absolute; left: 0; right: 0; bottom: 0; padding: 0 24px 22px; }
.timeline { display: flex; justify-content: center; gap: 10px; margin-bottom: 12px; }
.dot {
  width: 12px; height: 12px; border-radius: 50%;
  border: 1px solid rgba(255,255,255,0.35); background: transparent;
  transition: all .3s;
}
.dot.done { background: rgba(227,197,107,.5); border-color: var(--gold); }
.dot.active { background: var(--gold); border-color: var(--gold); transform: scale(1.35); box-shadow: 0 0 12px rgba(227,197,107,.7); }

.caption { padding: 18px 24px 14px; max-width: 860px; margin: 0 auto; }
.cap-head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.chip {
  font-size: 11px; padding: 2px 10px; border-radius: 999px;
  background: rgba(91,141,214,.18); color: var(--blue);
  border: 1px solid rgba(91,141,214,.4); text-transform: uppercase; letter-spacing: 1px;
}
.caption h2 { font-size: 19px; }
.caption em { color: var(--text-dim); font-size: 13px; }
.caption p { margin: 8px 0 12px; font-size: 14.5px; color: #d7dce9; }
.cap-foot { display: flex; align-items: center; gap: 14px; }
.pbar { flex: 1; height: 4px; border-radius: 4px; background: rgba(255,255,255,.12); overflow: hidden; }
.fill { height: 100%; background: linear-gradient(90deg, var(--blue), var(--gold)); transition: width .1s linear; }
.counter { font-size: 12px; color: var(--text-dim); white-space: nowrap; }
.controls { display: flex; gap: 8px; }

.paused {
  position: absolute; left: 50%; top: 45%; transform: translate(-50%, -50%);
  text-align: center; padding: 22px 36px;
}
.paused p { margin-bottom: 12px; color: var(--text-dim); }
</style>
