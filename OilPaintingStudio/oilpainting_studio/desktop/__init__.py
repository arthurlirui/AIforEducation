"""PaintingStudio Desktop — 论文 demo 实例 (设计文档 docs/paintingstudio_desktop_demo.md)。

双端架构:
- 计算层: PaintingStudioDemoEngine — YOLO/DA-V2 可用则真模型推理 (GPU/CPU),
  缺依赖时 mock 降级; 三档设备策略 gpu→cpu→mock 自动回退
- UI 层: 复用 gui/dist 前端 (Vue3+Three.js), pywebview 桌面窗口承载

启动:  py -m oilpainting_studio.desktop   (窗口)
        PYSTUDIO_DEMO=web py -m oilpainting_studio.desktop  (浏览器 http://127.0.0.1:8712)
"""
