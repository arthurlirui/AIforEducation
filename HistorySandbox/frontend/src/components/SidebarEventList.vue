<script setup>
defineProps({ events: { type: Array, default: () => [] }, currentId: String, loading: Boolean })
const emit = defineEmits(['select'])
</script>

<template>
  <aside class="sidebar panel">
    <header class="brand">
      <h1>读史 <span>HistorySandbox</span></h1>
      <p class="tagline">AI 沉浸式历史沙盘 · 看见历史的每一次转折</p>
    </header>

    <div class="list" v-if="!loading">
      <button
        v-for="ev in events"
        :key="ev.id"
        class="event-card"
        :class="{ active: ev.id === currentId }"
        @click="emit('select', ev.id)"
      >
        <div class="ev-top">
          <span class="ev-cover">{{ ev.cover || '📖' }}</span>
          <span class="ev-scale" :data-scale="ev.scale">{{ {world:'世界',region:'区域',country:'国家'}[ev.scale] || ev.scale }}</span>
        </div>
        <h2>{{ ev.title }}</h2>
        <p class="sub">{{ ev.subtitle }}</p>
        <p class="meta">{{ ev.year_start }} — {{ ev.year_end }} · {{ ev.step_count }} 幕推演</p>
      </button>
      <p v-if="!events.length" class="empty">暂无剧本，请先启动后端服务。</p>
    </div>
    <p v-else class="empty">正在加载剧本…</p>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 300px;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.brand {
  padding: 18px 18px 12px;
  border-bottom: 1px solid var(--border);
}
.brand h1 {
  margin: 0;
  font-size: 22px;
  letter-spacing: 2px;
  color: var(--accent);
}
.brand h1 span {
  font-size: 12px;
  color: var(--text-dim);
  letter-spacing: 1px;
  margin-left: 6px;
}
.tagline { margin: 6px 0 0; font-size: 12px; color: var(--text-dim); }
.list { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 10px; }
.event-card {
  text-align: left;
  padding: 14px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid var(--border);
  color: var(--text);
}
.event-card:hover { background: rgba(255, 255, 255, 0.08); transform: translateY(-1px); }
.event-card.active {
  border-color: var(--accent);
  background: rgba(241, 196, 15, 0.08);
  box-shadow: 0 0 18px rgba(241, 196, 15, 0.15);
}
.ev-top { display: flex; justify-content: space-between; align-items: center; }
.ev-cover { font-size: 22px; }
.ev-scale {
  font-size: 11px; padding: 2px 8px; border-radius: 10px;
  background: rgba(77, 163, 255, 0.15); color: var(--accent-2);
}
.event-card h2 { margin: 8px 0 4px; font-size: 16px; }
.sub { margin: 0 0 6px; font-size: 12px; color: var(--text-dim); }
.meta { margin: 0; font-size: 11px; color: var(--accent); opacity: 0.9; }
.empty { padding: 20px; text-align: center; color: var(--text-dim); font-size: 13px; }
</style>
