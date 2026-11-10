/**
 * Frontend 单元测试：hyperframes 插件纯函数。
 * 不测 DOM 交互（需要 jsdom），只测 framesToHTML / renderBlock 输出结构。
 */
import { framesToHTML, renderBlock, escapeHtml, isSafeSvg } from '../src/plugin/hyperframes.js'
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

test('escapeHtml 转义双引号和单引号（属性上下文防逃逸）', () => {
  assert.strictEqual(escapeHtml('"'), '&#34;')
  assert.strictEqual(escapeHtml("'"), '&#39;')
  const out = escapeHtml('" onmouseover="alert(1)')
  assert(!out.includes('"'))
})

// renderBlock: text
test('renderBlock text 渲染 markdown h2', () => {
  const html = renderBlock({ type: 'text', md: '## 标题', fragment: 0 })
  assert(html.includes('<h2>标题</h2>'))
  assert(html.includes('fragment'))
})

test('renderBlock text 注入被转义（XSS 防护）', () => {
  const html = renderBlock({ type: 'text', md: '<img src=x onerror=alert(1)>', fragment: 0 })
  assert(!html.includes('<img'))
  assert(html.includes('&lt;img src=x onerror=alert(1)&gt;'))
})

test('renderBlock text 属性注入经转义不逃逸', () => {
  const html = renderBlock({ type: 'text', md: '" onmouseover="alert(1)' })
  assert(!html.includes('" onmouseover'))
  assert(html.includes('&#34; onmouseover=&#34;alert(1)'))
})

test('renderBlock text 渲染 bold/italic/code/列表/引用', () => {
  const html = renderBlock({ type: 'text', md: '**粗** 和 *斜* 和 `code`\n- 项目\n> 引用' })
  assert(html.includes('<strong>粗</strong>'))
  assert(html.includes('<em>斜</em>'))
  assert(html.includes('<code>code</code>'))
  assert(html.includes('<li>项目</li>'))
  assert(html.includes('<blockquote>引用</blockquote>'))
})

test('renderBlock text 空行分隔的列表为 ul 分组', () => {
  const html = renderBlock({ type: 'text', md: '- a\n- b\n\n普通行' })
  assert(html.includes('<ul><li>a</li><li>b</li></ul>'))
  assert(html.includes('普通行'))
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

// renderBlock: motionCanvas SVG 白名单（B1）
test('isSafeSvg 拒绝脚本/事件/协议注入', () => {
  assert(isSafeSvg('<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>'))
  assert(!isSafeSvg('<script>alert(1)</script>'))
  assert(!isSafeSvg('<svg onload="alert(1)"></svg>'))
  assert(!isSafeSvg('<svg><a href="javascript:alert(1)"></a></svg>'))
  assert(!isSafeSvg('<svg><script/></svg>'))
  assert(!isSafeSvg(null))
  assert(!isSafeSvg(123))
})

test('renderBlock motionCanvas 恶意 fallbackSvg 被拒绝渲染', () => {
  const html = renderBlock({ type: 'motionCanvas', sceneRef: 'x', fallbackSvg: '<svg onload="alert(1)"><script/></svg>' })
  assert(!html.includes('onload'))
  assert(!html.includes('<script'))
  assert(html.includes('未通过安全校验'))
})

test('renderBlock motionCanvas 合法 fallbackSvg 正常内嵌', () => {
  const svg = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>'
  const html = renderBlock({ type: 'motionCanvas', sceneRef: 'x', fallbackSvg: svg })
  assert(html.includes(svg))
})

// renderBlock: quiz
test('renderBlock quiz 含选项和提交按钮', () => {
  const html = renderBlock({ type: 'quiz', q: '选哪个?', opts: ['A', 'B'], answer: 0, why: '因为', fragment: 0 })
  assert(html.includes('quiz-submit'))
  assert(html.includes('value="0"'))
  assert(html.includes('value="1"'))
})

test('renderBlock quiz 选项文本被转义', () => {
  const html = renderBlock({ type: 'quiz', q: 'q', opts: ['<b>x</b>'], answer: 0 })
  assert(!html.includes('<b>x</b>'))
  assert(html.includes('&lt;b&gt;x&lt;/b&gt;'))
})

test('renderBlock 多个 quiz 拥有独立单选组（F3）', () => {
  const h1 = renderBlock({ type: 'quiz', q: 'q1', opts: ['A'], answer: 0 })
  const h2 = renderBlock({ type: 'quiz', q: 'q2', opts: ['B'], answer: 0 })
  const n1 = h1.match(/name="([^"]+)"/)[1]
  const n2 = h2.match(/name="([^"]+)"/)[1]
  assert(n1 !== n2)
  assert(n1.startsWith('quiz-') && n2.startsWith('quiz-'))
})

test('renderBlock quiz data-answer 属性转义', () => {
  const html = renderBlock({ type: 'quiz', q: 'q', opts: ['A'], answer: '" onmouseover="x' })
  assert(!html.includes('" onmouseover="x"'))
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

test('framesToHTML 坏块渲染为错误占位不炸整课（S1）', () => {
  const frames = [{
    id: 'x#0', index: 0, title: 'T', layout: 'title',
    blocks_json: JSON.stringify([null, { type: 'text', md: 'ok' }]),
  }]
  const html = framesToHTML(frames)
  assert(html.includes('block-error'))
  assert(html.includes('渲染失败'))
  assert(html.includes('ok'))
  assert(html.includes('<section'))
})

test('framesToHTML 容错非数组 blocks_json', () => {
  const html = framesToHTML([{ id: 'x#0', index: 0, title: 'T', layout: 'title', blocks_json: '{"a":1}' }])
  assert(html.includes('<section'))
})

test('renderBlock code data-lang 属性转义', () => {
  const html = renderBlock({ type: 'code', lang: '"><script>', src: 'x' })
  assert(!html.includes('"><script>'))
  assert(html.includes('data-lang="&#34;&gt;&lt;script&gt;"'))
})

// 结果
console.log(`\n${passed} passed, ${failed} failed`)
if (failed > 0) process.exit(1)
