<template>
  <div class="app">
    <!-- 顶栏 -->
    <header class="topbar">
      <span class="logo">TechLearnStudio</span>
      <nav>
        <button @click="view = 'library'" :class="{ active: view === 'library' }">课程库</button>
        <input v-if="view === 'library'" v-model="searchQ" placeholder="搜索…" @keyup.enter="doSearch" />
      </nav>
    </header>

    <!-- 课程库视图 -->
    <div v-if="view === 'library'" class="library">
      <div v-if="loading" class="loading">加载中…</div>
      <div v-else-if="courses.length === 0" class="empty">暂无课程。请先运行 Studio 推送内容。</div>
      <div v-else class="course-grid">
        <div v-for="c in courses" :key="c.id" class="course-card" @click="openCourse(c.id)">
          <h3>{{ c.title }}</h3>
          <span class="badge">{{ c.category === 'language' ? '编程语言' : '专业课' }}</span>
          <span class="subject">{{ c.subject }}</span>
          <span class="frames-count">{{ c.frames_count }} 帧 · v{{ c.version }}</span>
        </div>
      </div>
      <div v-if="searchResults" class="search-info">搜索"{{ searchResults.query }}"：{{ searchResults.results.length }} 条</div>
    </div>

    <!-- 播放视图 -->
    <div v-if="view === 'player'" class="player-view">
      <aside class="outline">
        <button class="back-btn" @click="backToLibrary">← 返回</button>
        <h4>{{ currentCourse?.title }}</h4>
        <ul>
          <li v-for="f in currentFrames" :key="f.id"
              :class="{ active: currentFrameIndex === f.index }"
              @click="goToFrame(f.index)">
            {{ f.index }}. {{ f.title }}
          </li>
        </ul>
      </aside>
      <div class="slide-area" ref="slideArea" v-html="slidesHTML"></div>
    </div>
  </div>
</template>

<script>
import { framesToHTML, bindInteractions } from './plugin/hyperframes.js'

const API_BASE = ''  // vite proxy 转发 /api → backend

export default {
  data() {
    return {
      view: 'library',
      courses: [],
      loading: false,
      searchQ: '',
      searchResults: null,
      currentCourse: null,
      currentFrames: [],
      currentFrameIndex: 0,
      slidesHTML: '',
      revealInstance: null,
    }
  },
  async mounted() {
    await this.loadCourses()
  },
  methods: {
    async loadCourses() {
      this.loading = true
      try {
        const r = await fetch(`${API_BASE}/api/courses`)
        this.courses = await r.json()
      } catch (e) {
        console.error('加载课程失败', e)
        this.courses = []
      }
      this.loading = false
    },
    async doSearch() {
      if (!this.searchQ) { this.searchResults = null; return }
      const r = await fetch(`${API_BASE}/api/search?q=${encodeURIComponent(this.searchQ)}`)
      this.searchResults = await r.json()
    },
    async openCourse(id) {
      this.view = 'player'
      const [courseRes, framesRes] = await Promise.all([
        fetch(`${API_BASE}/api/courses/${id}`),
        fetch(`${API_BASE}/api/courses/${id}/frames`),
      ])
      this.currentCourse = await courseRes.json()
      this.currentFrames = await framesRes.json()
      this.renderSlides()
    },
    renderSlides() {
      this.slidesHTML = framesToHTML(this.currentFrames)
      this.$nextTick(() => this.initReveal())
    },
    async initReveal() {
      // 动态加载 reveal.js（CDN）
      if (!window.Reveal) {
        await this.loadScript('https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.js')
        await this.loadScript('https://cdn.jsdelivr.net/npm/reveal.js@5/plugin/highlight/highlight.es5.js')
        await this.loadScript('https://cdn.jsdelivr.net/npm/reveal.js@5/plugin/notes/notes.es5.js')
      }
      const Reveal = window.Reveal
      if (this.revealInstance) {
        this.revealInstance.destroy()
      }
      Reveal.initialize({
        controls: true,
        progress: true,
        slideNumber: true,
        hash: true,
        embedded: true,
        plugins: [window.RevealHighlight, window.RevealNotes],
      }).then(() => {
        this.revealInstance = Reveal
        const sections = document.querySelectorAll('.reveal .slides section')
        bindInteractions(Reveal, sections, this.currentFrames, API_BASE)
        Reveal.addEventListener('slidechanged', (e) => {
          this.currentFrameIndex = e.indexh
        })
      })
    },
    loadScript(src) {
      return new Promise((resolve, reject) => {
        const s = document.createElement('script')
        s.src = src
        s.onload = resolve
        s.onerror = reject
        document.head.appendChild(s)
      })
    },
    goToFrame(idx) {
      if (this.revealInstance) this.revealInstance.slide(idx)
      this.currentFrameIndex = idx
    },
    backToLibrary() {
      if (this.revealInstance) { this.revealInstance.destroy(); this.revealInstance = null }
      this.view = 'library'
      this.loadCourses()
    },
  },
}
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: system-ui, sans-serif; background: #1a1a2e; color: #eee; }

.topbar { display: flex; align-items: center; gap: 1rem; padding: 0.5rem 1rem; background: #16213e; }
.logo { font-weight: bold; font-size: 1.2rem; color: #e94560; }
.topbar nav { display: flex; gap: 0.5rem; align-items: center; }
.topbar button { background: none; border: 1px solid #444; color: #eee; padding: 0.3rem 0.8rem; border-radius: 4px; cursor: pointer; }
.topbar button.active { background: #e94560; border-color: #e94560; }
.topbar input { background: #0f0f23; border: 1px solid #444; color: #eee; padding: 0.3rem 0.6rem; border-radius: 4px; }

.library { padding: 2rem; }
.loading, .empty { text-align: center; padding: 3rem; color: #888; }
.course-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1rem; }
.course-card { background: #16213e; border: 1px solid #333; border-radius: 8px; padding: 1.2rem; cursor: pointer; transition: border-color 0.2s; }
.course-card:hover { border-color: #e94560; }
.course-card h3 { margin-bottom: 0.5rem; }
.badge { display: inline-block; background: #e94560; color: #fff; font-size: 0.75rem; padding: 0.1rem 0.5rem; border-radius: 3px; margin-right: 0.5rem; }
.subject { color: #aaa; font-size: 0.85rem; }
.frames-count { display: block; margin-top: 0.5rem; color: #888; font-size: 0.8rem; }

.player-view { display: flex; height: calc(100vh - 50px); }
.outline { width: 240px; background: #16213e; padding: 1rem; overflow-y: auto; border-right: 1px solid #333; }
.outline h4 { margin-bottom: 0.8rem; color: #e94560; }
.outline ul { list-style: none; }
.outline li { padding: 0.3rem 0.5rem; cursor: pointer; border-radius: 4px; font-size: 0.85rem; color: #ccc; }
.outline li:hover { background: #1a1a2e; }
.outline li.active { background: #e94560; color: #fff; }
.back-btn { margin-bottom: 1rem; background: none; border: 1px solid #444; color: #eee; padding: 0.3rem 0.8rem; border-radius: 4px; cursor: pointer; }

.slide-area { flex: 1; overflow: hidden; }
.slide-area .reveal { width: 100%; height: 100%; }

.block-callout { padding: 0.8rem; border-radius: 6px; margin: 0.5rem 0; font-size: 0.9rem; }
.callout-tip { background: #1a3a1a; border-left: 4px solid #4f4; }
.callout-warn { background: #3a3a1a; border-left: 4px solid #ff4; }
.callout-pitfall { background: #3a1a1a; border-left: 4px solid #f44; }
.block-code { margin: 0.5rem 0; }
.block-code pre { background: #0d1117; padding: 0.8rem; border-radius: 6px; overflow-x: auto; }
.run-btn { margin-top: 0.5rem; background: #238636; color: #fff; border: none; padding: 0.3rem 1rem; border-radius: 4px; cursor: pointer; }
.run-output { margin-top: 0.5rem; }
.run-output pre { background: #0d1117; padding: 0.5rem; border-radius: 4px; font-size: 0.85rem; }
.block-link { display: inline-block; margin-top: 1rem; color: #58a6ff; cursor: pointer; }
.block-quiz { margin: 0.5rem 0; }
.block-quiz label { display: block; padding: 0.2rem 0; }
.quiz-submit { margin-top: 0.5rem; background: #238636; color: #fff; border: none; padding: 0.3rem 1rem; border-radius: 4px; cursor: pointer; }
</style>
