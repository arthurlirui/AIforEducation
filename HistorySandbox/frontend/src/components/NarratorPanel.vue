<script setup>
import { ref, watch, nextTick, onMounted } from 'vue'

const props = defineProps({
  eventId: String,
  stepId: Number,
})
const emit = defineEmits(['ask'])

const text = ref('')
const typing = ref(false)
const shown = ref('')
const answers = ref([])   // { question, answer, source }
const input = ref('')
const listEl = ref(null)

// generation token: a newer typeOut() cancels any in-progress older one,
// so rapid step switches never interleave two narrations.
let typeToken = 0

async function typeOut(target, ms = 30) {
  const token = ++typeToken
  typing.value = true
  shown.value = ''
  for (let i = 0; i < target.length; i++) {
    if (token !== typeToken) return
    shown.value += target[i]
    // eslint-disable-next-line no-await-in-loop
    await new Promise((r) => setTimeout(r, ms))
  }
  if (token === typeToken) typing.value = false
}

// request tokens: a stale response (e.g. a slow LLM reply for step 1 arriving
// after the user already switched to step 2) must be discarded, otherwise it
// would overwrite the newer narration/answer.
let fetchToken = 0
let askToken = 0

async function fetchNarration() {
  if (!props.eventId || !props.stepId) return
  const my = ++fetchToken
  const mod = await import('../api.js')
  try {
    const n = await mod.fetchNarration(props.eventId, props.stepId, 'immersive')
    if (my !== fetchToken) return   // superseded by a newer request — drop it
    await typeOut(n.text, 14)
  } catch {
    if (my === fetchToken) {
      typeToken++              // cancel any in-flight typing
      typing.value = false
      shown.value = '（讲解服务暂时不可用，请确认后端已启动。）'
    }
  }
}

// 换事件（stepId 不变时 watch 不触发）与换步骤都要重新拉取旁白
watch(() => [props.eventId, props.stepId], fetchNarration)
onMounted(fetchNarration)

async function submit() {
  const q = input.value.trim()
  if (!q) return
  input.value = ''
  const my = ++askToken
  typeToken++                 // cancel any in-flight narration typing
  typing.value = false
  answers.value.push({ question: q, answer: '…', source: 'pending' })
  const idx = answers.value.length - 1
  await nextTick()
  listEl.value?.scrollTo({ top: 1e6, behavior: 'smooth' })
  const mod = await import('../api.js')
  try {
    const res = await mod.askAI(props.eventId, props.stepId, q)
    answers.value[idx] = res            // captured idx: always the right slot
    if (my !== askToken) return         // but a newer reply owns the typewriter
    await typeOut(res.answer, 12)
  } catch {
    answers.value[idx] = {
      question: q, answer: '（问答服务暂时不可用）', source: 'local',
    }
  }
  await nextTick()
  listEl.value?.scrollTo({ top: 1e6, behavior: 'smooth' })
}
</script>

<template>
  <section class="narrator panel">
    <header>
      <span class="ai-dot pulse" />
      <b>AI 讲解员</b>
      <span class="hint">切换到任意一幕，我将为你讲述；也可以向我提问</span>
    </header>

    <div class="body" ref="listEl">
      <p class="narration" :class="{ caret: typing }">{{ shown }}</p>
      <div v-for="(a, i) in answers" :key="i" class="qa">
        <p class="q">🙋 {{ a.question }}</p>
        <p v-if="i === answers.length - 1 && typing" class="a caret">{{ shown }}</p>
        <p v-else class="a">{{ a.answer }}</p>
      </div>
    </div>

    <div class="ask">
      <input
        v-model="input"
        placeholder="例如：为什么孙权决定联刘抗曹？"
        @keyup.enter="submit"
      />
      <button @click="submit" :disabled="!input.trim()">提问</button>
    </div>
  </section>
</template>

<style scoped>
.narrator {
  position: absolute;
  left: 318px;
  bottom: 130px;
  width: 360px;
  display: flex;
  flex-direction: column;
  max-height: 42vh;
  padding: 0;
  overflow: hidden;
}
header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}
header b { color: var(--accent); }
.hint { font-size: 10px; color: var(--text-dim); }
.ai-dot {
  width: 9px; height: 9px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 8px var(--accent);
}
.body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 14px;
  font-size: 12.5px;
  line-height: 1.8;
}
.narration { margin: 0 0 10px; color: var(--text); white-space: pre-wrap; }
.qa { margin-bottom: 10px; }
.q { margin: 0 0 4px; color: var(--accent-2); font-size: 12px; }
.a { margin: 0; color: var(--text); }
.ask {
  display: flex;
  gap: 8px;
  padding: 10px;
  border-top: 1px solid var(--border);
}
.ask input {
  flex: 1;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text);
  padding: 8px 10px;
  font-size: 12px;
  outline: none;
}
.ask input:focus { border-color: var(--accent); }
.ask button {
  background: var(--accent);
  color: #1a1400;
  padding: 0 14px;
  font-size: 12px;
}
.ask button:disabled { opacity: 0.4; }
</style>
