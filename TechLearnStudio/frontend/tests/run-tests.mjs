/**
 * Frontend 单元测试：hyperframes 插件纯函数。
 * 不测 DOM 交互（需要 jsdom），只测 framesToHTML / renderBlock 输出结构。
 */
import { framesToHTML, renderBlock, escapeHtml } from '../src/plugin/hyperframes.js'
import assert from 'assert'

let passed = 0, failed = 0

function test(name, fn) {
  try { fn(); console.log(`  ✓ ${name}`); passed++ }
  catch (e) { console.error(`  ✗ ${name}: ${e.message}`); failed++ }
}

// escapeHtml
test('escapeHtml 转义 <>&', () => {
  assert.strictEqual(escapeHtml('<script>'), '&lt;script&gt;')
  assert.strictEqual(escapeHtml('a & b'), 'a &amp; b')
})

// renderBlock: text
test('renderBlock text 渲染 markdown h2', () => {
  const html = renderBlock({ type: 'text', md: '## 标题', fragment: 0 })
  assert(html.includes('<h2>标题</h2>'))
  assert(html.includes('fragment'))
})

// renderBlock: code
test('renderBlock code 含 runnable 按钮', () => {
  const html = renderBlock({ type: 'code', lang: 'python', src: 'print(1)', runnable: true, fragment: 0 })
  assert(html.includes('class="run-btn"'))
  assert(html.includes('print(1)'))
  assert(html.includes('language-python'))
})

// renderBlock: code 不 runnable 无按钮
test('renderBlock code 非 runnable 无按钮', () => {
  const html = renderBlock({ type: 'code', lang: 'rust', src: 'fn main(){}', runnable: false })
  assert(!html.includes('run-btn'))
})

// renderBlock: formula
test('renderBlock formula 含 tex 容器', () => {
  const html = renderBlock({ type: 'formula', tex: 'y=x', explain: '定义', fragment: 0 })
  assert(html.includes('data-tex="y=x"'))
  assert(html.includes('formula-explain'))
})

// renderBlock: callout
test('renderBlock callout pitfall 含警告样式', () => {
  const html = renderBlock({ type: 'callout', kind: 'pitfall', md: '别这样', fragment: 0 })
  assert(html.includes('callout-pitfall'))
})

// renderBlock: motionCanvas
test('renderBlock motionCanvas 含 sceneRef', () => {
  const html = renderBlock({ type: 'motionCanvas', sceneRef: 'convolution', params: {}, renderMode: 'video', fallbackSvg: '<svg/>', fragment: 0 })
  assert(html.includes('data-mc-block="convolution"'))
})

// renderBlock: quiz
test('renderBlock quiz 含选项和提交按钮', () => {
  const html = renderBlock({ type: 'quiz', q: '选哪个?', opts: ['A', 'B'], answer: 0, why: '因为', fragment: 0 })
  assert(html.includes('quiz-submit'))
  assert(html.includes('value="0"'))
  assert(html.includes('value="1"'))
})

// renderBlock: link
test('renderBlock link 含 data-frame-link', () => {
  const html = renderBlock({ type: 'link', to: 'course#5', label: '下一帧' })
  assert(html.includes('data-frame-link="course#5"'))
  assert(html.includes('下一帧'))
})

// framesToHTML
test('framesToHTML 生成 reveal 结构', () => {
  const frames = [
    { id: 'c#0', course_id: 'c', index: 0, title: '封面', layout: 'title', blocks_json: JSON.stringify([{ type: 'text', md: '# Hi' }]) },
    { id: 'c#1', course_id: 'c', index: 1, title: '代码', layout: 'code-focus', blocks_json: JSON.stringify([{ type: 'code', lang: 'python', src: 'x=1', runnable: true }]) },
  ]
  const html = framesToHTML(frames)
  assert(html.includes('<div class="reveal">'))
  assert(html.includes('class="slides"'))
  assert(html.includes('data-frame-id="c#0"'))
  assert(html.includes('data-layout="code-focus"'))
  assert(html.includes('run-btn'))
})

test('framesToHTML 容错空 blocks_json', () => {
  const html = framesToHTML([{ id: 'x#0', index: 0, title: 'T', layout: 'title', blocks_json: '[]' }])
  assert(html.includes('<section'))
})

// 结果
console.log(`\n${passed} passed, ${failed} failed`)
if (failed > 0) process.exit(1)
