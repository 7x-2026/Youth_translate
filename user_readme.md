# 课堂同传使用指南（macOS / Windows）

这个项目会用电脑麦克风采音，经本机服务发送到火山引擎，网页显示中英实时字幕。需要联网和已开通“同声传译2.0”的**豆包语音新版 API Key**；使用云端服务可能产生费用。网页只在这台电脑的 `http://localhost:8765` 打开。

**日常使用不用运行 `npm run dev`。** 项目根目录没有 `package.json`，直接在根目录运行这条命令也不会启动网站。第一次安装时构建一次网页，以后在项目根目录运行 `uv run --locked python -m backend`，保持终端开着，再打开浏览器。前端开发命令是 `npm --prefix frontend run dev`，单独运行它不能连接翻译后端。

## macOS：第一次安装

1. 把整个项目文件夹放到电脑上；文件夹里应能看到 `pyproject.toml`、`frontend`、`backend`、`.env.example`。如果是从另一台电脑复制，`.env` 可能没有一同复制，需要在本机重新配置。
2. 从 [Node.js 官网](https://nodejs.org/en/download)安装 **LTS 版**（建议 24 LTS，安装包同时包含 npm）。从 [uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/)安装 uv：在“终端”运行下列命令，然后关闭并重新打开终端。

   ```sh
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

3. 在 Finder 找到项目文件夹。打开“终端”，输入 `cd `（末尾有空格），把文件夹拖进终端窗口，再按回车。运行 `ls`，确认能看到 `pyproject.toml` 和 `frontend`。以下命令都在这个**项目根目录**运行。
4. 安装 Python 环境和网页依赖，再构建网页。uv 会按要求自动取得 Python 3.12，无须另装系统 Python。

   ```sh
   uv sync --locked --python 3.12
   npm --prefix frontend ci
   npm --prefix frontend run build
   ```

5. 如果根目录还没有 `.env`，运行 `cp .env.example .env`；**已有 `.env` 就跳过，不要覆盖里面的 Key**。运行 `open -e .env` 打开配置文件：首次配置时，将 `VOLC_API_KEY=` 后面填入自己的豆包语音 Key，并把 `VOLC_SUBTITLE_RESPONSE_MODE=unverified` 改为 `VOLC_SUBTITLE_RESPONSE_MODE=delta`，保存；如果现有 `.env` 已可用，就不必修改。其他行保持原样。不要使用火山方舟的 `ark-` Key，也不要把 Key 写进前端文件或发到聊天中。Key 可从[豆包语音控制台](https://console.volcengine.com/speech/new/setting/apikeys?projectName=default)获取；对应项目还须开通同声传译2.0。
6. 启动服务，终端窗口保持打开：

   ```sh
   uv run --locked python -m backend
   ```

7. 用 Chrome 或 Edge 打开 **http://localhost:8765**，点击“开始课程”，允许浏览器和系统使用麦克风。默认优先电脑内置麦克风；也能从“麦克风”下拉框选 iPhone 或外接设备。“收音方式”中的“教室 · 远距离”适合试用较远位置，但环境噪声也可能更多。结束时点击网页“结束”，再在终端按 `Ctrl+C` 关闭本机服务。

## Windows：第一次安装（PowerShell）

Windows 路径已按 PowerShell 编写；项目尚未在 Windows 实机验收。

1. 把整个项目文件夹放到电脑上，确认根目录有 `pyproject.toml`、`frontend`、`backend`、`.env.example`。
2. 从 [Node.js 官网](https://nodejs.org/en/download)安装 **Windows LTS 安装包**（建议 24 LTS，包含 npm）。按照 [uv 官方说明](https://docs.astral.sh/uv/getting-started/installation/)安装 uv：打开 PowerShell，运行 `winget install --id=astral-sh.uv -e`。若电脑没有 `winget`，可使用官方提供的 PowerShell 安装命令：

   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```

   安装后关闭并重新打开 PowerShell；`node --version`、`npm --version`、`uv --version` 应显示版本号。
3. 在文件资源管理器进入项目文件夹，点击地址栏，输入 `powershell` 并按回车。新窗口应处于项目根目录；运行 `Get-ChildItem pyproject.toml,frontend` 确认位置。
4. 安装 Python 环境和网页依赖，再构建网页。uv 会按要求自动取得 Python 3.12。

   ```powershell
   uv sync --locked --python 3.12
   npm --prefix frontend ci
   npm --prefix frontend run build
   ```

5. 如果还没有 `.env`，运行 `Copy-Item .env.example .env`；**已有 `.env` 就跳过**。运行 `notepad .env`：首次配置时填入 `VOLC_API_KEY=` 的豆包语音 Key，并将 `VOLC_SUBTITLE_RESPONSE_MODE=unverified` 改为 `VOLC_SUBTITLE_RESPONSE_MODE=delta`，保存；现有 `.env` 已可用时不必修改。Key 所属项目须开通同声传译2.0。不要使用 `ark-` Key。
6. 启动服务，保持 PowerShell 窗口打开：

   ```powershell
   uv run --locked python -m backend
   ```

7. 用 Chrome 或 Edge 打开 **http://localhost:8765**，点击“开始课程”并允许麦克风。默认优先电脑内置麦克风，可在下拉框手动改选。结束时点击网页“结束”，再在 PowerShell 按 `Ctrl+C`。

## 第二次及以后

安装和构建完成后，每次只需在**项目根目录**（能看到 `pyproject.toml` 的 `translate` 文件夹）打开终端或 PowerShell，运行。不要先 `cd backend`；那样 Python 找不到顶层 `backend` 包。

```text
uv run --locked python -m backend
```

然后打开 **http://localhost:8765**。如果网页已经能打开，就说明服务可能已在运行，**不必再启动第二个**。更换 `.env` 后重启服务；代码更新后重新执行对应系统的 `uv sync --locked --python 3.12`、`npm --prefix frontend ci`、`npm --prefix frontend run build`。字幕历史只在当前网页内存里；需要保存时，结束前点击“导出 TXT”，刷新网页会清空当前记录。

## 常见问题

- **`npm run dev` 可以吗？** 根目录直接运行会报错。开发者可以分别运行 `uv run --locked python -m backend` 和 `npm --prefix frontend run dev`，再访问 `http://localhost:5173`。普通使用按上面的单服务方式即可。
- **`uv`、`node` 或 `npm` 显示找不到？** 安装后重新打开终端/PowerShell，分别运行 `uv --version`、`node --version`、`npm --version` 检查。
- **提示 `address already in use`？** 先打开 `http://localhost:8765`；如果页面正常，不用再次启动。要重启时，回到正在运行服务的终端按 `Ctrl+C`，再在项目根目录运行启动命令。不要随意结束占用端口的未知进程。
- **提示 `No module named backend`？** 当前在 `backend` 子目录；先运行 `cd ..` 回到能看到 `pyproject.toml` 的项目根目录，再启动。
- **浏览器打不开 8765？** 确认启动命令仍在运行、是在项目根目录执行。不要把地址改成电脑局域网 IP；服务只开放给本机浏览器。
- **页面显示“未就绪”或 401/403？** 检查 `.env` 是否保存、`VOLC_SUBTITLE_RESPONSE_MODE=delta`、Key 是否来自豆包语音新版控制台、同一项目是否开通同声传译2.0；改完后重启服务。凭证不要发给他人。
- **没有字幕或输入电平？** 在浏览器和系统设置中允许麦克风，检查网页显示的实际输入源和下拉框选择。Mac 可能把 iPhone 当系统默认输入，但本项目会优先识别电脑内置麦克风。“云端等待语音”表示云端暂未检测到语音，并不表示电脑静音。
- **声音离电脑较远？** 试“教室 · 远距离”模式，或把外接麦克风放到讲话者附近。网页输入电平显示的是数字音频电平，不代表云端一定能识别每句话。

开发与协议维护说明见 [AI_readme.md](AI_readme.md)。
