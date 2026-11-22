# 工作台V2 · 目录级指令

你当前的工作目录是主项目文件夹。**上层的完整指令在 `../AGENTS.md`，先读它**（因为本工作区没有 git 仓库，
从子目录打开时上层文件不会自动注入，所以这里只放真正必须遵守的要点和索引）。

## 唯一真身

`index.html` / `app.js` / `app.css`。`*.bak_*` 是历史备份，只读、不改、不当基线。
`data/*.js` 由 `tools/build_*.py` 生成，不要手改。

## 跑与验

- 启动：双击 `启动工作台.bat` → `http://127.0.0.1:8199/`
- 改前端：Ctrl+F5 即生效；改 `tools/cors_proxy.py`：必须重启 bat
- 改 `app.js` 后：`node --check app.js`，再跑 `../_scratch/cdp_*.mjs` 里对应那条

请用下面的显式指令把背景读全（在本目录下它们不会自动加载）：

1. 读 `../.workbuddy/memory/MEMORY.md`（整份，用户偏好与创作规范）
2. 读 `../.workbuddy/memory/TECH.md` 的**定向章节**：先 `grep -n "^## " ` 找章节号再读，不要整份读（119KB，超注入预算）
3. 读 `../.workbuddy/memory/` 下最近一天的日志，了解上一轮改到哪
4. 功能语义查 `说明.md`

## 红线

- 生图 / 上下文预设是用户浏览器 localStorage 里的数据：代码不得播种、迁移、覆盖
- 不要把 API Key、服务账号私钥写进任何文件
- 不要删除 `../.workbuddy/`
