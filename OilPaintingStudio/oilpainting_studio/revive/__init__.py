"""revive — OilPaintingRevive 管线 (单幅油画 → 4 模块 Canvas3D).

迁自原 OilPaintingRevive/src/oilrev/. 4 模块对应 IJCAI'26 论文 Canvas3D:
- ``stage1`` PaintParse — YOLO 分割 + Depth Anything V2 深度
- ``stage2`` MonoSplat — TripoSplat 单图→3DGS + 2DGS 转换
- ``stage3`` SketchComp — 线稿解析 + 重定位 + SD 修复
- ``stage4`` 多视角关键帧渲染
- ``stage5`` ArtiFlow — Wan2.2 / LTX ControlNet 视频合成
- ``schemas`` — pydantic 数据模型
- ``cli`` — click CLI 入口
"""
