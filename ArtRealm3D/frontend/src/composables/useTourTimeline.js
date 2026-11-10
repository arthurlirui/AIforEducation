/**
 * useTourTimeline — 导览章节时间线的纯逻辑 composable。
 *
 * 只管"当前章 + 计时 + 进度"状态机，不依赖组件/DOM/真实定时器：
 * 组件用 setInterval 周期调用 tick(dtMs) 驱动，单测可直接调 tick，
 * 确定性、无需 fake timers。这正是导览计时器历史 bug 的高发区，
 * 抽出来才能被测试守住。
 *
 * 状态机约定：
 *  - start()   从第 0 章开始播放
 *  - resume()  从暂停继续：进度归零、章节重开完整时长（进度条与章节
 *              定时器同步重启，避免"进度条先到 100% 冻结、章节还在播"的失拍）
 *  - next()/prev()/goto(i) 切章：自动重臂（进度与计时归零，按新章时长走）
 *  - tick(dtMs) 播放中推进进度；本章时长走完自动切下一章；
 *              末章走完触发 hooks.onTourEnd 并停止播放
 */
import { ref, computed } from 'vue'

export function useTourTimeline(chapters, hooks = {}) {
  const chapterIndex = ref(0)
  const playing = ref(false)
  const progress = ref(0)
  let elapsed = 0 // 当前章节已播放的毫秒数（非响应式：只有 progress 需要渲染）

  const currentChapter = computed(() => chapters.value?.[chapterIndex.value] ?? null)

  function durationMs(c) {
    return Math.max(1, (c?.duration ?? 15) * 1000)
  }

  /** 进入第 idx 章：索引 + 进度 + 计时全部归零（"切章重臂"） */
  function _enter(idx) {
    chapterIndex.value = idx
    progress.value = 0
    elapsed = 0
  }

  /** 切到下一章；已在末章时返回 false（去向由调用方决定，如转跳测验） */
  function next() {
    const n = chapters.value?.length ?? 0
    if (chapterIndex.value < n - 1) {
      _enter(chapterIndex.value + 1)
      return true
    }
    return false
  }

  function prev() {
    if (chapterIndex.value > 0) {
      _enter(chapterIndex.value - 1)
      return true
    }
    return false
  }

  function goto(i) {
    const n = chapters.value?.length ?? 0
    if (i >= 0 && i < n) _enter(i)
  }

  function start() {
    _enter(0)
    playing.value = true
  }

  function pause() {
    playing.value = false
  }

  function resume() {
    // 报告判定：章节定时器重开完整时长，进度条必须同步从 0 重走
    progress.value = 0
    elapsed = 0
    playing.value = true
  }

  /** 推进 dtMs 毫秒；播放中才有效。本章播完自动切章（末章则结束） */
  function tick(dtMs = 100) {
    if (!playing.value) return
    elapsed += dtMs
    const dur = durationMs(currentChapter.value)
    progress.value = Math.min(1, elapsed / dur)
    if (elapsed >= dur) {
      if (!next()) {
        playing.value = false
        hooks.onTourEnd?.()
      }
    }
  }

  return { chapterIndex, playing, progress, currentChapter, next, prev, goto, start, pause, resume, tick }
}
