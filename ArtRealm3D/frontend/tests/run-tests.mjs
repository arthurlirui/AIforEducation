/**
 * Frontend 纯逻辑测试：useTourTimeline composable（导览章节时间线）。
 *
 * 不测 DOM/Three.js（需要浏览器），只测时间线状态机——这正是导览计时器
 * 历史 bug 的高发区。无定时器依赖：直接调 tick(dtMs)，完全确定性。
 *
 * 运行：cd frontend && npm test   （即 node tests/run-tests.mjs）
 */
import { useTourTimeline } from '../src/composables/useTourTimeline.js'
import { ref } from 'vue'
import assert from 'assert'

let passed = 0, failed = 0

function test(name, fn) {
  try { fn(); console.log(`  ✓ ${name}`); passed++ }
  catch (e) { console.error(`  ✗ ${name}: ${e.message}`); failed++ }
}

const chapters = [
  { id: 'intro', duration: 1 },
  { id: 'mid', duration: 2 },
  { id: 'end', duration: 1 },
]

// 切章重臂：手动切章后进度归零、按新章节时长重新计时
test('切章重臂：goto 后进度归零并按新章时长推进', () => {
  const t = useTourTimeline(ref(chapters))
  t.start()
  assert.strictEqual(t.chapterIndex.value, 0)
  t.tick(100)
  assert.ok(t.progress.value > 0 && t.progress.value < 1, '进度应已部分推进')

  t.goto(1) // 手动切到第 2 章
  assert.strictEqual(t.chapterIndex.value, 1)
  assert.strictEqual(t.progress.value, 0, '切章后进度必须归零（重臂）')

  t.tick(2000) // 第 2 章时长 2s：走完自动切到第 3 章
  assert.strictEqual(t.chapterIndex.value, 2, '新章时长走完应自动切章')
  assert.strictEqual(t.progress.value, 0, '自动切章后进度归零')
  assert.ok(t.playing.value)
})

// 暂停恢复：resume 重置进度，与章节完整时长同步（报告判定的失拍修复）
test('暂停恢复：resume 后进度归零、与章节完整时长同步', () => {
  const t = useTourTimeline(ref(chapters))
  t.start()
  t.tick(500) // 第 1 章时长 1s，走到一半
  assert.ok(Math.abs(t.progress.value - 0.5) < 1e-9, '暂停前进度应为 0.5')

  t.pause()
  t.tick(500) // 暂停中 tick 不生效
  assert.strictEqual(t.playing.value, false)
  assert.ok(Math.abs(t.progress.value - 0.5) < 1e-9, '暂停中进度不得变化')

  t.resume() // 继续：进度归零、重开完整时长（修复"进度条从旧值继续走"失拍）
  assert.strictEqual(t.progress.value, 0, 'resume 必须重置进度')
  assert.strictEqual(t.playing.value, true)

  t.tick(1000) // 完整时长 1s 走完 → 与进度条同时到达终点并切章
  assert.strictEqual(t.chapterIndex.value, 1, '完整时长走完应恰好切章')
  assert.strictEqual(t.progress.value, 0)
})

// 末章转跳：末章播完触发 onTourEnd 并停止播放
test('末章转跳：末章播完触发 onTourEnd 且停止播放', () => {
  let ended = false
  const t = useTourTimeline(ref(chapters), { onTourEnd: () => { ended = true } })
  t.start()
  t.goto(2) // 直达末章
  assert.strictEqual(t.chapterIndex.value, 2)

  t.tick(999) // 还差 1ms 到时
  assert.ok(!ended && t.playing.value, '未到完整时长不得提前结束')

  t.tick(1)
  assert.ok(ended, '末章播完必须触发 onTourEnd（转跳测验）')
  assert.strictEqual(t.playing.value, false, '结束后停止播放')
  assert.strictEqual(t.chapterIndex.value, 2, '末章索引保持不变')

  // 停止后 tick 不再产生任何效果
  t.tick(5000)
  assert.ok(!t.playing.value)
})

// 结果
console.log(`\n${passed} passed, ${failed} failed`)
if (failed > 0) process.exit(1)
