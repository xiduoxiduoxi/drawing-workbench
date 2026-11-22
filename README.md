# 绘图工作台 · AI 选词 + ComfyUI 出图

面向本地 [ComfyUI](https://github.com/comfyanonymous/ComfyUI) 的**提示词工作台**：在浏览器里写词、管词库、配预设，一键把工作流提交到本机 ComfyUI 出图。

前端是零构建的原生 HTML/CSS/JS（无框架、无 npm、无打包器）；后端只有一个几百行的 Python 标准库脚本，负责静态托管 + 同源反代。

## 快速开始

需要：Python 3.9+、本机已运行的 ComfyUI（默认 `127.0.0.1:8188`）。

```bash
# Windows 直接双击
启动工作台.bat

# 或手动
python tools/cors_proxy.py 8199 --open
```

浏览器打开 http://127.0.0.1:8199/ 即为工作台本体。

`启动工作台.bat` 会优先使用 `F:\ComfyUI-aki-v3\python\python.exe`，路径不存在时自动回退到系统 `python`——其他人拿到仓库不用改脚本就能跑。

## 为什么需要本地反代

ComfyUI 只监听 8188 且不带 CORS 头，页面从别的端口发请求会被浏览器拦。`tools/cors_proxy.py` 用同一个源把两件事做完：

| 路径 | 行为 |
|---|---|
| `/` | 托管仓库内的静态文件 |
| `/comfy/*` | 转发到 `http://127.0.0.1:8188/*`（工作流提交、进度轮询、图片读取） |
| `/relay/*` | 通用直通：把请求转给 `X-Relay-Target` 头里的地址，用于浏览器直连会被 Origin 白名单拦下的外部接口 |

只依赖 Python 标准库。改了这个脚本必须重启进程才生效。

## 目录结构

```
index.html  app.js  app.css     唯一真身：界面 / 逻辑 / 样式
启动工作台.bat                   启动入口（静态托管 + 反代 + 自动开浏览器）
data/                           自动生成的词库（tags / templates / presets / characters / mosslib / positions …）
tools/build_*.py                词库数据管线；改词库改这里，不要手改 data/*.js
tools/zhsrc  tools/mosssrc      词库源数据（角色、版权、中文 tag 映射等）
tools/cors_proxy.py             本地服务
说明.md                         功能语义与操作说明
清洗报告.md                     数据管线的变更记录
```

`data/*.js` 由 `tools/build_*.py` 生成，重新跑脚本即覆盖，因此不要手动编辑。

## 功能概览

- **提示词工作台**：结构化录入（角色 / 服装 / 场景 / 镜头 / 动作），实时拼装成单行 prompt，可复制或直接送进工作流。
- **词库**：本地中文 tag 库 + 角色库 + 姿势库，支持搜索、点选、组合模板。
- **生图预设**：底模、LoRA 链、采样参数、分辨率等整套配置，支持导入导出 JSON。
- **接口预设**：可接任意兼容 OpenAI / Gemini 风格的接口做「AI 选词」「需求扩写」等辅助，配置存在浏览器 localStorage。
- **历史浏览**：直接读 ComfyUI 的 output 目录，缩略图浏览、回填提示词与 LoRA。

## 数据与隐私

- 所有配置（预设、接口 Key、上下文预设）存在**浏览器 localStorage**，不入库、不上传。
- 前端只与本机 `127.0.0.1` 通信；除了你自己填的外部模型接口地址，不向任何第三方发数据。
- 仓库里不含任何密钥；`index.html` 中的 service account 片段是占位示例。

## 许可

未指定许可证。如需复用请先开 issue 联系作者。
