<script setup>
import { computed } from 'vue'

const props = defineProps({
  style: { type: Object, required: true },
  selected: { type: Boolean, default: false },
})
const emit = defineEmits(['select'])

const artists = computed(() => (props.style.reference_artists || []).join(' · '))
</script>

<template>
  <div
    class="card style-card"
    :class="{ selected }"
    @click="emit('select', style.id)"
  >
    <div style="display:flex; justify-content:space-between; align-items:start;">
      <h3 style="color:var(--primary-dark); margin-bottom:4px;">{{ style.name }}</h3>
      <span class="badge">{{ style.era }}</span>
    </div>
    <p style="color:var(--text-light); font-size:13px; margin-bottom:10px;">
      {{ style.name_en }}
    </p>
    <p style="font-size:14px; margin-bottom:10px;">{{ style.description }}</p>
    <p v-if="artists" style="font-size:13px; color:var(--text-light);">
      代表艺术家：{{ artists }}
    </p>
  </div>
</template>
