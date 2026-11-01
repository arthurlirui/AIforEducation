<script setup>
defineProps({ playing: Boolean })
const emit = defineEmits(['toggle'])
</script>

<template>
  <button v-if="!playing" class="hint-play pulse" @click="emit('toggle')">
    ▶ 开始推演
  </button>
</template>

<style scoped>
.hint-play {
  position: absolute;
  top: 18px;
  left: 318px;
  padding: 10px 22px;
  background: var(--accent);
  color: #1a1400;
  font-size: 14px;
  font-weight: 600;
  border-radius: 22px;
  box-shadow: 0 4px 18px rgba(241, 196, 15, 0.4);
  z-index: 5;
}
.hint-play:hover { filter: brightness(1.1); transform: translateY(-1px); }
</style>
