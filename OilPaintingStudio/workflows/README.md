# 自定义工作流覆盖

把从 ComfyUI 网页端「保存（API 格式）」导出的 JSON 放到这里，文件名与内置模板一致即可覆盖：

- `img2img_oilpaint.json` —— 关键帧油画化
- `ltx_i2v.json`          —— LTX-Video 图生视频
- `wan_i2v.json`          —— Wan2.2-I2V 图生视频

## 节点 id 约定

管线按节点 id 注入参数，请保持以下 id 不变（其余节点可自由增删）：

**img2img_oilpaint**: `ckpt` `lora` `latent` `prompt_pos` `prompt_neg` `sampler` `save`
**ltx_i2v**: `input_image` `ltx_model` `ltx_pos` `ltx_neg` `ltx_sampler` `ltx_save`
**wan_i2v**: `input_image` `wan_model` `wan_pos` `wan_neg` `wan_sampler` `wan_save`

注入的字段名见 `src/oilpaint/pipeline/keyframe.py` 与 `animate.py`。
