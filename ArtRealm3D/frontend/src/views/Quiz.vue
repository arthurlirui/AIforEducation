<script setup>
import { onMounted, ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchMasterpiece, submitQuiz } from '../api'

const route = useRoute()
const router = useRouter()
const data = ref(null)
const answers = ref([])
const result = ref(null)
const submitted = ref(false)
const error = ref('')

const allAnswered = computed(() =>
  data.value && answers.value.length === data.value.quiz.length && answers.value.every((a) => a !== null && a !== undefined),
)
const scoreColor = computed(() => {
  if (!result.value) return ''
  const s = result.value.score
  return s >= 0.8 ? '#7ed491' : s >= 0.5 ? '#e3c56b' : '#e88a7a'
})

function choose(qi, oi) {
  if (submitted.value) return
  answers.value[qi] = oi
}

async function submit() {
  try {
    result.value = await submitQuiz(data.value.id, answers.value)
    submitted.value = true
    window.scrollTo({ top: 0, behavior: 'smooth' })
  } catch (e) {
    error.value = `提交失败: ${e.message}`
  }
}

onMounted(async () => {
  try {
    data.value = await fetchMasterpiece(route.params.id)
    answers.value = data.value.quiz.map(() => null)
  } catch (e) {
    error.value = `加载失败: ${e.message}`
  }
})
</script>

<template>
  <div class="page">
    <header class="head">
      <router-link to="/" class="back">← 目录</router-link>
      <router-link :to="`/painting/${route.params.id}`" class="back">↺ 重新导览</router-link>
    </header>

    <div v-if="error" class="panel error">{{ error }}</div>

    <template v-if="data">
      <section class="intro panel">
        <h1>学习检验</h1>
        <p>{{ data.title }} · {{ data.artist }}</p>
        <p class="dim">刚刚的沉浸之旅你记住了多少？</p>
      </section>

      <div v-if="submitted && result" class="score panel" :style="{ borderColor: scoreColor }">
        <div class="big" :style="{ color: scoreColor }">{{ result.correct }} / {{ result.total }}</div>
        <p>得分 {{ Math.round(result.score * 100) }} 分</p>
        <p class="dim verdict">
          {{ result.score === 1 ? '完美！你真正读懂了这幅画。'
             : result.score >= 0.7 ? '不错！再回顾一下错题对应的章节吧。'
             : '值得再走进画中一次——沉浸导览值得重温。' }}
        </p>
      </div>

      <div
        v-for="(q, qi) in data.quiz"
        :key="qi"
        class="qcard panel"
        :class="{
          right: submitted && result.per_question[qi].correct,
          wrong: submitted && !result.per_question[qi].correct,
        }"
      >
        <h3>{{ qi + 1 }}. {{ q.q }}</h3>
        <div class="options">
          <button
            v-for="(opt, oi) in q.options"
            :key="oi"
            class="opt"
            :class="{
              picked: answers[qi] === oi,
              correct: submitted && oi === q.answer,
              wrongPicked: submitted && answers[qi] === oi && oi !== q.answer,
            }"
            @click="choose(qi, oi)"
          >{{ opt }}</button>
        </div>
        <p v-if="submitted" class="explain">💡 {{ q.explain }}</p>
      </div>

      <div class="actions">
        <button v-if="!submitted" class="btn primary" :disabled="!allAnswered" @click="submit">交卷</button>
        <button v-else class="btn primary" @click="router.push('/')">探索更多名画 →</button>
        <span v-if="!submitted && !allAnswered" class="dim">答完所有题目后交卷</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; margin-bottom: 20px; }
.back { color: var(--text-dim); font-size: 14px; }
.back:hover { color: var(--gold); }

.error { padding: 18px 24px; margin-bottom: 20px; color: #ffb4a8; }
.intro { text-align: center; padding: 28px; margin-bottom: 24px; }
.intro h1 { letter-spacing: 4px; }
.intro .dim { color: var(--text-dim); font-size: 14px; }

.score { text-align: center; padding: 28px; margin-bottom: 24px; border-width: 2px; }
.score .big { font-size: 52px; font-weight: 700; }
.verdict { font-size: 15px; }

.qcard { padding: 22px 26px; margin-bottom: 18px; border-left: 3px solid transparent; }
.qcard.right { border-left-color: #7ed491; }
.qcard.wrong { border-left-color: #e88a7a; }
.qcard h3 { font-size: 16.5px; margin-bottom: 14px; }
.options { display: grid; gap: 10px; }
.opt {
  text-align: left; padding: 11px 18px; border-radius: 10px;
  border: 1px solid var(--line); background: rgba(255,255,255,.03);
  color: var(--text); font-size: 14.5px; transition: all .2s;
}
.opt:hover:not(:disabled) { border-color: rgba(91,141,214,.6); transform: translateX(3px); }
.opt.picked { border-color: var(--gold); background: rgba(227,197,107,.1); }
.opt.correct { border-color: #7ed491; background: rgba(126,212,145,.12); }
.opt.wrongPicked { border-color: #e88a7a; background: rgba(232,138,122,.12); }
.explain { margin-top: 12px; font-size: 13.5px; color: var(--text-dim); }

.actions { text-align: center; margin: 28px 0; }
.actions .btn:disabled { opacity: .45; cursor: not-allowed; }
.dim { color: var(--text-dim); font-size: 13px; margin-left: 12px; }
</style>
