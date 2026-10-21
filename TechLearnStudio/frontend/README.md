# TechLearnStudio frontend

Vue 3 + Vite + TypeScript 外壳 + **reveal.js 5.x** 渲染课件。

- `src/plugin/` — 自研 hyperframes 插件层（~250 行 TS）：frames.json → reveal `<section>`、跨帧超链接路由、sandbox 运行按钮绑定、Motion Canvas block 挂载。不重新实现幻灯内核。
- `src/motion-canvas/` — Motion Canvas 集成：`@motion-canvas/player` Web Component 包装、video/live 双模式切换、与 reveal.js fragments 的事件桥接。
- `src/components/` — 顶栏、大纲、课程库等 Vue 壳组件。
- 动画分两路：简单顺序开关走 reveal.js fragments；帧精确原理动画（卷积/OFDM/注意力等）走 Motion Canvas，后端预渲染 mp4 或实时 player，前端嵌入。

设计稿阶段，尚未初始化脚手架。详见 `../../docs/modules/techlearnstudio.md` §5。
