<script setup>
const props = defineProps({
  steps: { type: Array, default: () => [] },
  current: Number,
  playing: Boolean,
})
const emit = defineEmits(['select', 'toggle-play', 'prev', 'next', 'restart'])
</script>

<template>
  <footer class="timeline panel">
    <div class="controls">
      <button class="ctl" title="重播" @click="emit('restart')">⟲</button>
      <button class="ctl" title="上一幕" :disabled="current <= 1" @click="emit('prev')">◀</button>
      <button class="ctl play" :title="playing ? '暂停' : '播放'" @click="emit('toggle-play')">
        {{ playing ? '❚❚' : '▶' }}
      </button>
      <button class="ctl" title="下一幕" :disabled="current >= steps.length" @click="emit('next')">▶</button>
    </div>

    <div class="track">
      <div
        v-for="s in steps"
        :key="s.id"
        class="node"
        :class="{ active: s.id === current, done: s.id < current }"
        @click="emit('select', s.id)"
      >
        <div class="dot" />
        <div class="card">
          <span class="date">{{ s.date }}</span>
          <span class="title">{{ s.title }}</span>
        </div>
      </div>
      <div class="rail">
        <div class="fill" :style="{ width: `${((current - 1) / Math.max(1, steps.length - 1)) * 100}%` }" />
      </div>
    </div>
  </footer>
</template>

<style scoped>
.timeline {
  position: absolute;
  left: 50%;
  bottom: 18px;
  transform: translateX(-50%);
  width: min(880px, calc(100% - 340px));
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 12px 20px;
}
.controls { display: flex; gap: 8px; }
.ctl {
  width: 38px; height: 38px;
  background: rgba(255, 255, 255, 0.06);
  color: var(--text);
  font-size: 14px;
  border: 1px solid var(--border);
}
.ctl:hover:not(:disabled) { background: rgba(255, 255, 255, 0.14); }
.ctl.play {
  width: 46px;
  background: var(--accent);
  color: #1a1400;
  font-size: 15px;
  border-color: transparent;
}
.ctl.play:hover { filter: brightness(1.1); }

.track {
  position: relative;
  flex: 1;
  height: 84px;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.rail {
  position: absolute;
  top: 10px; left: 8px; right: 8px;
  height: 3px;
  background: rgba(255, 255, 255, 0.12);
  border-radius: 2px;
}
.fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent-2), var(--accent));
  border-radius: 2px;
  transition: width 0.5s ease;
}
.node {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  cursor: pointer;
  padding-top: 0;
  min-width: 60px;
}
.dot {
  width: 14px; height: 14px;
  border-radius: 50%;
  background: #2a3355;
  border: 2px solid rgba(255, 255, 255, 0.3);
  margin-top: 3px;
  transition: all 0.2s;
}
.node.done .dot { background: var(--accent-2); border-color: var(--accent-2); }
.node.active .dot {
  background: var(--accent);
  border-color: var(--accent);
  box-shadow: 0 0 12px var(--accent);
  transform: scale(1.25);
}
.card {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  opacity: 0.45;
  transition: opacity 0.2s;
}
.node:hover .card, .node.active .card { opacity: 1; }
.date { font-size: 10px; color: var(--accent); white-space: nowrap; }
.title {
  font-size: 11px;
  color: var(--text);
  max-width: 110px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
