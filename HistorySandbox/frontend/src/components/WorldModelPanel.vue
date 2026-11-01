<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  event: Object,
  step: Object,
  mode: String,          // '' | 'move' | 'attack' | 'alliance' | 'retreat' | 'hypothetical'
  selectedActorId: String,
  busy: Boolean,
})
const emit = defineEmits(['set-mode', 'select-actor', 'cancel', 'submit-hypothetical', 'exit'])

const hypText = ref('')
const error = ref('')

const actors = computed(() => props.step?.actors || [])
const selectedActor = computed(() => actors.value.find(a => a.id === props.selectedActorId))
const hasEnemies = computed(() => {
  const as = actors.value
  return as.some(a => a.nation !== as[0]?.nation)
})

function pick(id) { emit('select-actor', id) }

function submitHyp() {
  const q = hypText.value.trim()
  if (!q) return
  error.value = ''
  emit('submit-hypothetical', q)
}
</script>

<template>
  <section class="worldmodel panel">
    <header>
      <span class="wm-icon pulse">🧠</span>
      <b>世界模型 · 交互推演</b>
      <button class="close" title="退出交互模式" @click="emit('exit')">✕</button>
    </header>

    <!-- no mode yet: choose an intervention -->
    <div v-if="!mode" class="choose">
      <p class="hint">选择一种方式干预沙盘，世界模型将推演 consequences（结果标记为 ✦ 假想，非史实）：</p>
      <div class="btns">
        <button @click="emit('set-mode', 'move')">♟ 机动<br /><i>指挥棋子移动</i></button>
        <button @click="emit('set-mode', 'attack')">⚔ 进攻<br /><i>向最近敌军开战</i></button>
        <button @click="emit('set-mode', 'alliance')">🤝 结盟<br /><i>改变外交格局</i></button>
        <button @click="emit('set-mode', 'retreat')">🛡 后撤<br /><i>保存实力转移</i></button>
        <button class="wide" @click="emit('set-mode', 'hypothetical')">✦ 假想推演<br /><i>"如果没有东南风会怎样？"</i></button>
      </div>
    </div>

    <!-- actor-picking modes -->
    <div v-else-if="mode === 'move' || mode === 'attack' || mode === 'retreat'" class="picking">
      <p class="hint">
        {{ {move:'点击沙盘上的棋子选中它', attack:'选择发动进攻的棋子（将打击最近的敌军）', retreat:'选择要后撤的棋子'}[mode] }}
      </p>
      <div class="actor-list">
        <button
          v-for="a in actors" :key="a.id"
          class="actor" :class="{ sel: a.id === selectedActorId }"
          @click="pick(a.id)"
        >
          <span class="dot" :style="{ background: (event.nations.find(n=>n.id===a.nation)||{}).color }" />
          {{ a.name }}
          <i>兵力 {{ a.strength }}</i>
        </button>
      </div>
      <p v-if="mode === 'move' && selectedActorId" class="hint ok">已选中「{{ selectedActor?.name }}」— 现在点击沙盘上的目标位置</p>
      <p v-else-if="mode === 'attack' && !hasEnemies" class="hint warn">
        ⚠ 此幕沙盘上只有单一阵营，没有可进攻的敌军。试试「机动」或「✦ 假想推演」。
      </p>
      <p v-else-if="(mode === 'attack' || mode === 'retreat') && selectedActorId" class="hint ok">
        已选中「{{ selectedActor?.name }}」— 点击「执行推演」
      </p>
      <div class="row">
        <button class="primary" :disabled="!selectedActorId || busy || (mode === 'attack' && !hasEnemies)" @click="emit('submit-hypothetical', null, mode)">
          {{ busy ? '推演中…' : '执行推演' }}
        </button>
        <button @click="emit('cancel')">返回</button>
      </div>
    </div>

    <!-- alliance mode -->
    <div v-else-if="mode === 'alliance'" class="picking">
      <p class="hint">选择要缔结同盟的势力：</p>
      <div class="actor-list">
        <button
          v-for="n in event.nations" :key="n.id"
          class="actor" :class="{ sel: n.id === selectedActorId }"
          @click="pick(n.id)"
        >
          <span class="dot" :style="{ background: n.color }" />
          {{ n.name }}
          <i>{{ n.side }}</i>
        </button>
      </div>
      <div class="row">
        <button class="primary" :disabled="!selectedActorId || busy" @click="emit('submit-hypothetical', null, 'alliance')">
          {{ busy ? '推演中…' : '缔结假想同盟' }}
        </button>
        <button @click="emit('cancel')">返回</button>
      </div>
    </div>

    <!-- hypothetical free-text -->
    <div v-else-if="mode === 'hypothetical'" class="picking">
      <p class="hint">向世界模型提出你的反事实假想（结果为 ✦ 假想推演，非史实）：</p>
      <textarea
        v-model="hypText"
        rows="3"
        placeholder="例如：如果曹操没有铁索连舰，火攻还能成功吗？"
      />
      <div class="row">
        <button class="primary" :disabled="!hypText.trim() || busy" @click="submitHyp">
          {{ busy ? '推演中…' : '✦ 启动假想推演' }}
        </button>
        <button @click="emit('cancel')">返回</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.worldmodel {
  position: absolute;
  top: 18px;
  left: 50%;
  transform: translateX(-50%);
  width: 480px;
  padding: 0;
  overflow: hidden;
  z-index: 6;
}
header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}
header b { color: var(--accent); flex: 1; }
.wm-icon { font-size: 15px; }
.close {
  background: transparent; color: var(--text-dim); font-size: 13px; padding: 2px 8px;
}
.close:hover { color: var(--text); }
.choose { padding: 12px 14px; }
.hint { margin: 0 0 10px; font-size: 11.5px; color: var(--text-dim); line-height: 1.6; }
.hint.ok { color: var(--accent); }
.hint.warn { color: #ffb4a8; }
.btns { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
.btns button {
  padding: 10px 6px;
  background: rgba(255,255,255,0.05);
  border: 1px solid var(--border);
  color: var(--text);
  font-size: 12px;
  line-height: 1.5;
}
.btns button:hover:not(:disabled) { background: rgba(241,196,15,0.12); border-color: var(--accent); }
.btns button.wide { grid-column: span 4; }
.btns i { font-style: normal; font-size: 10px; color: var(--text-dim); display: block; }
.picking { padding: 12px 14px; }
.actor-list { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.actor {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 10px;
  background: rgba(255,255,255,0.05);
  border: 1px solid var(--border);
  color: var(--text);
  font-size: 11.5px;
}
.actor.sel { border-color: var(--accent); background: rgba(241,196,15,0.12); }
.actor i { font-style: normal; font-size: 10px; color: var(--text-dim); }
.dot { width: 9px; height: 9px; border-radius: 3px; }
.row { display: flex; gap: 8px; margin-top: 4px; }
.row .primary {
  flex: 1;
  background: var(--accent);
  color: #1a1400;
  font-size: 12.5px;
  padding: 9px;
  font-weight: 600;
}
.row .primary:disabled { opacity: 0.45; }
.row button:not(.primary) {
  background: rgba(255,255,255,0.06);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 9px 16px;
  font-size: 12px;
}
textarea {
  width: 100%;
  background: rgba(255,255,255,0.06);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  padding: 8px 10px;
  font-size: 12px;
  font-family: inherit;
  resize: vertical;
  outline: none;
  margin-bottom: 8px;
}
textarea:focus { border-color: var(--accent); }
</style>
