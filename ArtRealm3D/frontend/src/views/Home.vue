<script setup>
import { onMounted, ref, computed } from 'vue'
import { fetchCatalog } from '../api'

const catalog = ref([])
const error = ref('')

// layered 3D tilt preview on hover
function tilt(e, el) {
  const r = el.getBoundingClientRect()
  const x = ((e.clientX - r.left) / r.width - 0.5) * 14
  const y = ((e.clientY - r.top) / r.height - 0.5) * -10
  el.style.transform = `perspective(700px) rotateY(${x}deg) rotateX(${y}deg) translateY(-4px)`
  const layers = el.querySelectorAll('.mini-layer')
  layers.forEach((l, i) => {
    l.style.transform = `translate(${x * (i + 1) * 0.9}px, ${y * (i + 1) * 0.7}px)`
  })
}
function untilt(el) {
  el.style.transform = ''
  el.querySelectorAll('.mini-layer').forEach((l) => (l.style.transform = ''))
}

onMounted(async () => {
  try {
    catalog.value = await fetchCatalog()
  } catch (e) {
    error.value = `加载失败: ${e.message}（请确认后端已启动在 8300 端口）`
  }
})

const gradient = (pal) => `linear-gradient(135deg, ${pal.join(', ')})`
</script>

<template>
  <div class="page">
    <section class="hero">
      <h1>艺境 <span class="en">ArtRealm3D</span></h1>
      <p class="tagline">走进世界名画的三维空间 · 在沉浸导览中读懂它的背景与精神内核</p>
      <p class="sub">
        每幅画被解构为多层三维画层——天空、大地、人物各自独立呼吸；
        章节式镜头将带你从构图分析走向精神内核，最后以测验巩固所学。
      </p>
    </section>

    <div v-if="error" class="panel error">{{ error }}</div>

    <div class="grid">
      <router-link
        v-for="m in catalog"
        :key="m.id"
        :to="`/painting/${m.id}`"
        class="card panel"
        @mousemove="tilt($event, $event.currentTarget)"
        @mouseleave="untilt($event.currentTarget)"
      >
        <div class="thumb" :style="{ background: gradient(m.hero_palette) }">
          <div v-for="i in 3" :key="i" class="mini-layer" :style="{ zIndex: i, animationDelay: (i * 0.7) + 's' }"></div>
          <span class="movement">{{ m.movement }}</span>
        </div>
        <div class="body">
          <h3>{{ m.title }}</h3>
          <p class="artist">{{ m.artist }} · {{ m.year }}</p>
          <p class="summary">{{ m.summary }}</p>
          <div class="facts">
            <span>{{ m.layer_count }} 个三维画层</span>
            <span>{{ m.chapter_count }} 章导览</span>
          </div>
        </div>
      </router-link>
    </div>
  </div>
</template>

<style scoped>
.hero { text-align: center; padding: 48px 0 40px; }
.hero h1 { font-size: 44px; letter-spacing: 10px; }
.hero .en { font-size: 20px; color: var(--gold); letter-spacing: 2px; vertical-align: middle; }
.tagline { margin-top: 10px; font-size: 17px; color: var(--text-dim); }
.sub { margin: 14px auto 0; max-width: 620px; font-size: 14px; color: var(--text-dim); }

.error { padding: 18px 24px; margin: 20px auto; max-width: 640px; text-align: center; color: #ffb4a8; }

.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 26px; margin-top: 12px; }

.card { overflow: hidden; transition: transform .25s ease, border-color .25s ease; will-change: transform; }
.card:hover { border-color: rgba(227,197,107,.45); }

.thumb {
  position: relative; height: 190px; overflow: hidden; border-radius: var(--radius) var(--radius) 0 0;
  display: flex; align-items: center; justify-content: center;
}
.mini-layer {
  position: absolute; inset: -6%;
  background: radial-gradient(ellipse at center, rgba(255,255,255,.14), transparent 65%);
  border-radius: 50%;
  animation: pulse 4s ease-in-out infinite;
  transition: transform .25s ease;
}
@keyframes pulse { 0%,100% { opacity: .5 } 50% { opacity: 1 } }
.movement {
  position: absolute; bottom: 10px; right: 12px;
  font-size: 12px; padding: 3px 12px; border-radius: 999px;
  background: rgba(10,12,18,.55); border: 1px solid rgba(255,255,255,.22); backdrop-filter: blur(6px);
}

.body { padding: 18px 22px 20px; }
.body h3 { font-size: 21px; letter-spacing: 2px; }
.artist { color: var(--gold); font-size: 13px; margin: 2px 0 8px; }
.summary { font-size: 13.5px; color: var(--text-dim); min-height: 66px; }
.facts { display: flex; gap: 14px; margin-top: 12px; font-size: 12px; color: var(--blue); }
</style>
