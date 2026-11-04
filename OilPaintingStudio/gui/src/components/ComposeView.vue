<script setup>
// 视频合成 (§4.6): stage5 ComfyUI 工作流提交 + 任务进度
import { ref, onMounted } from 'vue'
import { api, waitTask } from '../api.js'

const props = defineProps({ project: Object })
const emit = defineEmits(['notify', 'notify-error', 'refresh'])

const model = ref('wan2.2')
const aspect = ref('16:9')
const depthWeight = ref(0.85)
const cannyWeight = ref(0.6)
const prompt = ref('')
const duration = ref(5)
const submitting = ref(false)
const progress = ref(0)
const taskLog = ref([])
const lastOutput = ref(null)

async function submit() {
  submitting.value = true; progress.value = 0; taskLog.value = []
  try {
    const { task_id } = await api.runCompose(props.project.project_id, {
      model: model.value, prompt: prompt.value, aspect: aspect.value,
      depth_weight: depthWeight.value, canny_weight: cannyWeight.value,
      duration_sec: duration.value,
    })
    const t = await waitTask(task_id, t => {
      progress.value = t.progress
      taskLog.value = t.log.slice(-6)
    }, 400, 600000)
    if (t.status === 'done') {
      lastOutput.value = t.result.output
      emit('notify', '合成完成 (ComfyUI 不可用时生成占位视频)', 'ok')
      emit('refresh')
    } else emit('notify', `合成失败: ${t.error || t.status}`, 'err')
  } catch (e) { emit('notify-error', e) }
  finally { submitting.value = false }
}

onMounted(() => { prompt.value = 'oil painting style, gentle motion' })
</script>

<template>
  <div style="flex:1;overflow:auto;padding:16px;display:flex;gap:16px;flex-wrap:wrap;align-content:flex-start">
    <!-- 参数表单 -->
    <div style="flex:1;min-width:300px;max-width:420px;display:flex;flex-direction:column;gap:12px">
      <b style="font-weight:600">合成参数 (stage5 ArtiFlow)</b>
      <div style="background:var(--panel);border:1px solid var(--bd);border-radius:10px;padding:12px;display:flex;flex-direction:column;gap:10px">
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
          <label style="display:flex;flex-direction:column;gap:4px" class="mini">
            I2V 模型
            <select v-model="model">
              <option value="wan2.2">Wan2.2-I2V (高质量)</option>
              <option value="ltx">LTX-Video (快)</option>
            </select>
          </label>
          <label style="display:flex;flex-direction:column;gap:4px" class="mini">
            画幅
            <select v-model="aspect"><option>16:9</option><option>9:16</option></select>
          </label>
        </div>
        <label class="mini" style="display:flex;flex-direction:column;gap:4px">
          Depth ControlNet 权重: {{ depthWeight.toFixed(2) }}
          <input type="range" min="0" max="1" step="0.05" v-model.number="depthWeight">
        </label>
        <label class="mini" style="display:flex;flex-direction:column;gap:4px">
          Canny ControlNet 权重: {{ cannyWeight.toFixed(2) }}
          <input type="range" min="0" max="1" step="0.05" v-model.number="cannyWeight">
        </label>
        <label class="mini" style="display:flex;flex-direction:column;gap:4px">
          时长 (秒)
          <input type="number" min="2" max="30" v-model.number="duration" style="width:100%">
        </label>
        <label class="mini" style="display:flex;flex-direction:column;gap:4px">
          提示词
          <textarea v-model="prompt" rows="3" style="width:100%;resize:vertical"></textarea>
        </label>
        <button class="btn pri" :disabled="submitting" @click="submit">
          {{ submitting ? `合成中 ${Math.round(progress*100)}%` : '提交合成' }}
        </button>
      </div>
      <div class="mini">
        ComfyUI 可用时走 revive.stage5 工作流 (Wan2.2/LTX + depth/canny 双控);
        不可用时生成占位视频保证流程闭环。产物写 stage5/runs/&lt;时间戳&gt;/。
      </div>
    </div>

    <!-- 任务面板 -->
    <div style="flex:1;min-width:300px;max-width:420px;display:flex;flex-direction:column;gap:12px">
      <b style="font-weight:600">任务进度</b>
      <div style="background:var(--panel);border:1px solid var(--bd);border-radius:10px;padding:12px;display:flex;flex-direction:column;gap:10px">
        <template v-if="submitting || taskLog.length">
          <div class="pbar"><i :style="{width: progress*100+'%'}"></i></div>
          <div class="mini" style="max-height:140px;overflow:auto">
            <div v-for="(l, i) in taskLog" :key="i" style="padding:1px 0">▸ {{ l }}</div>
          </div>
        </template>
        <div v-else class="mini">尚未提交合成任务。</div>
      </div>
      <template v-if="lastOutput">
        <b style="font-weight:600">输出</b>
        <div class="mini" style="word-break:break-all">{{ lastOutput }}</div>
      </template>
    </div>
  </div>
</template>
