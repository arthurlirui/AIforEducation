"""PaintingStudio GUI 后端。

按 docs/paintingstudio_gui_design.md §2–§4 实现：
- ``models``    : project.json / scene.json / undo 的 pydantic 数据模型（§3.3–3.4）
- ``store``     : 项目目录读写（原子写、版本翻版、快照）
- ``tasks``     : GPU 串行任务队列（进度/日志/取消）
- ``adapters``  : 对 revive stage1/stage2 算法的封装
- ``api``       : FastAPI routers（§3.5 读写 API 总表）
- ``server``    : FastAPI app 组装 + main 入口
"""
