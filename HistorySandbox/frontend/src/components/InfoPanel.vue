<script setup>
defineProps({
  event: Object,
  step: Object,
})
</script>

<template>
  <section v-if="event && step" class="info panel">
    <div class="head">
      <h2>{{ event.title }}</h2>
      <span class="era">{{ event.era }}</span>
    </div>

    <div class="step-head">
      <span class="step-no">第 {{ step.id }} 幕 / {{ event.steps.length }}</span>
      <span class="step-date" :class="{ hyp: step.hypothetical }">{{ step.date }}</span>
    </div>
    <slot name="badge" />
    <h3 class="step-title" :class="{ hyp: step.hypothetical }">{{ step.hypothetical ? '✦ ' : '' }}{{ step.title }}</h3>

    <div class="block">
      <h4>背景</h4>
      <p>{{ step.background || event.summary }}</p>
    </div>
    <div class="block">
      <h4>沙盘解说</h4>
      <p>{{ step.narrative }}</p>
    </div>
    <div v-if="step.spirit" class="block spirit">
      <h4>✦ 精神内核</h4>
      <p>{{ step.spirit }}</p>
    </div>
    <div v-if="step.significance" class="block">
      <h4>历史意义</h4>
      <p>{{ step.significance }}</p>
    </div>

    <div v-if="event.nations?.length" class="block">
      <h4>沙盘势力</h4>
      <div class="nation" v-for="n in event.nations" :key="n.id">
        <span class="swatch" :style="{ background: n.color }" />
        <b>{{ n.name }}</b>
        <i>{{ n.side }}</i>
        <p>{{ n.description }}</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.info {
  position: absolute;
  top: 18px; right: 18px;
  width: 340px;
  max-height: calc(100% - 160px);
  overflow-y: auto;
  padding: 18px;
}
.head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.head h2 { margin: 0; font-size: 18px; }
.era { font-size: 11px; color: var(--accent); }
.step-head { display: flex; justify-content: space-between; margin-top: 14px; }
.step-no { font-size: 11px; color: var(--text-dim); }
.step-date { font-size: 12px; color: var(--accent-2); }
.step-date.hyp { color: var(--accent); }
.step-title { margin: 4px 0 12px; font-size: 16px; color: var(--accent); }
.step-title.hyp { color: var(--accent); text-shadow: 0 0 12px rgba(241, 196, 15, 0.4); }
.block { margin-bottom: 12px; }
.block h4 {
  margin: 0 0 4px;
  font-size: 12px;
  color: var(--accent-2);
  letter-spacing: 1px;
}
.block p { margin: 0; font-size: 12.5px; line-height: 1.7; color: var(--text); }
.spirit {
  border-left: 3px solid var(--accent);
  padding-left: 10px;
  background: rgba(241, 196, 15, 0.05);
  border-radius: 0 8px 8px 0;
  padding-top: 2px; padding-bottom: 6px;
}
.spirit h4 { color: var(--accent); }
.nation { margin-top: 8px; font-size: 12px; }
.nation b { font-size: 12.5px; }
.nation i { font-style: normal; font-size: 10px; color: var(--text-dim); margin-left: 6px; }
.nation p { margin: 2px 0 0; font-size: 11px; color: var(--text-dim); line-height: 1.6; }
.swatch {
  display: inline-block;
  width: 10px; height: 10px;
  border-radius: 3px;
  margin-right: 6px;
}
</style>
