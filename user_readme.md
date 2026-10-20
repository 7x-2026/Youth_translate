# 课堂同传使用指南（macOS / Windows）

这个项目可以从麦克风或扬声器 / 耳机的内部音频采音，经本机服务发送到火山引擎，网页显示中英实时字幕。会议声音继续正常播放，同传不回放音频、不改变会议设备，也不需要共享屏幕。需要联网和已开通“同声传译2.0”的**豆包语音新版 API Key**；使用云端服务可能产生费用。网页只在这台电脑的 `http://localhost:8765` 打开。

**日常使用不用运行 `npm run dev`。** 项目根目录没有 `package.json`，直接在根目录运行这条命令也不会启动网站。第一次安装时构建一次网页，以后在项目根目录运行 `uv run --locked python -m backend`，保持终端开着，再打开浏览器。前端开发命令是 `npm --prefix frontend run dev`，单独运行它不能连接翻译后端。

## 别人复现前，需要准备什么

| 需要的东西 | 从哪里取得、用途 |
|---|---|
| 项目源码 | 从 [GitHub 仓库](https://github.com/7x-2026/Youth_translate)下载 ZIP 并解压；已安装 Git 的人也可以运行 `git clone https://github.com/7x-2026/Youth_translate.git`。进入解压或克隆后的项目根目录，确认能看到 `pyproject.toml`、`frontend` 和 `backend`。 |
| 本机软件 | Node.js LTS（含 npm）、uv、Chrome 或 Edge；uv 会在安装项目依赖时取得 Python 3.12。还需要可用的麦克风和互联网连接。macOS、Windows 的具体安装步骤见下文。 |
| 各自的云端权限 | 每位使用者需在**豆包语音新版控制台**取得自己的 API Key，并在该 Key 所属项目开通“同声传译2.0”（资源 `volc.service_type.10053`）。这是云端翻译，可能产生费用；火山方舟 `ark-` Key 不适用。 |
| 本机配置 | 仓库只提供不含密钥的 `.env.example`。每台电脑自行复制为 `.env`，填写 `VOLC_API_KEY`，并将 `VOLC_SUBTITLE_RESPONSE_MODE` 从 `unverified` 改为 `delta`（本项目当前接口已实测为增量字幕）。**不要把自己的 `.env` 或 Key 发给别人或提交到 GitHub。** |
| 本机生成物 | `.venv`、`frontend/node_modules`、`frontend/dist` 不在仓库中。下文的安装和构建命令会在使用者电脑上重新生成，无须从原作者电脑复制。 |

只想检查代码能否构建、自动测试能否通过时，**不需要 API Key**；但要看到真实翻译，必须具备自己的 Key、同一项目的服务权限、麦克风和网络。仓库里的 `tests/fixtures/ast_real_redacted.json` 是文字已脱敏的事件样本，**不是音频文件**，不能拿它直接试讲。

## macOS：第一次安装

1. 按上表从 GitHub 下载项目，或从另一台电脑复制项目文件夹；根目录应有 `pyproject.toml`、`frontend`、`backend`、`.env.example`。新电脑需要在本机创建自己的 `.env`。
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

7. 用 Chrome 或 Edge 打开 **http://localhost:8765**，点击“开始课程”，允许浏览器和系统使用麦克风。默认优先电脑内置麦克风；也能从“音频输入”下拉框选 iPhone 或外接设备。“收音方式”中的“教室 · 远距离”适合试用较远位置，但环境噪声也可能更多。会议声音的使用方法见下文。结束时点击网页“结束”，再在终端按 `Ctrl+C` 关闭本机服务。

## Windows：第一次安装（PowerShell）

Windows 路径已按 PowerShell 编写；项目尚未在 Windows 实机验收。

1. 按上表从 GitHub 下载项目，或从另一台电脑复制项目文件夹，确认根目录有 `pyproject.toml`、`frontend`、`backend`、`.env.example`。新电脑需要在本机创建自己的 `.env`。
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

安装和构建完成后，每次只需在**项目根目录**（能看到 `pyproject.toml` 的文件夹，名称可能是 `Youth_translate` 或 `translate`）打开终端或 PowerShell，运行。不要先 `cd backend`；那样 Python 找不到顶层 `backend` 包。

```text
uv run --locked python -m backend
```

然后打开 **http://localhost:8765**。如果网页已经能打开，就说明服务可能已在运行，**不必再启动第二个**。更换 `.env` 后重启服务；代码更新后重新执行对应系统的 `uv sync --locked --python 3.12`、`npm --prefix frontend ci`、`npm --prefix frontend run build`。字幕历史只在当前网页内存里；需要保存时，结束前点击“导出 TXT”，刷新网页会清空当前记录。

点击“开始课程”后，音频设备准备与翻译连接准备会并行进行，页面立即显示启动进度；设备就绪后才开始上传音频。首次系统授权可能仍需等待，首次字幕还取决于讲话内容和云端响应。

## 如何确认复现成功

1. **不连接云端的检查**：在项目根目录运行 `uv run --locked pytest -q`、`npm --prefix frontend test`、`npm --prefix frontend run build`。这些检查不需要 Key；它们不能代替真实麦克风联调。
2. **页面检查**：启动后访问 `http://localhost:8765/api/health`，应看到 `"ready":true`；再打开 `http://localhost:8765`，确认页面可显示。`ready` 只表示本机配置齐全，不代表云端已接受该 Key。若为 `false`，先检查 `.env`、Key 类型和字幕模式。
3. **真实翻译检查**：在网页点击“开始课程”，允许麦克风，朗读一句不含隐私的中文或英文测试句。页面应出现输入电平、原文和译文；结束后再检查最后一句是否定稿。只有这一步通过，才能说明此电脑的麦克风、网络、Key 和云端资源已一起接通。

若要复现协议探测，而非只试用网页，需**自己准备**不超过 60 秒的 16kHz、单声道、16-bit WAV 测试音频；仓库没有附带原始录音。把文件放在项目根目录并命名为 `test.wav` 后运行 `uv run --locked python -m scripts.probe test.wav --container pcm`。这会把测试音频发送至火山引擎，可能产生费用。不同录音的字幕段数和延迟不会与 [验证记录](tests/ACCEPTANCE.md) 中的历史样本相同。

## 开会时翻译耳机 / 扬声器里的声音

页面只有一个“音频输入”选择框，所有设备按硬件原名显示，分为“麦克风 / 输入设备”和“扬声器 / 耳机”两组。例如一副耳机既有麦克风又能播放声音时，会分别出现在对应组里。

1. 在 **扬声器 / 耳机** 组里，选择会议实际使用的输出设备，例如 **EDIFIER W830NB** 或 **MacBook Pro扬声器**。请选会议软件当前使用的那个设备；同传不会替你改变会议的输出设置。
2. 将方向选为 **English → 中文**，再点击开始。无需选择标签页或共享屏幕。同传直接读取发往该设备的数字音频，会议仍正常播放；耳机麦克风继续供会议软件使用，同传不会额外打开它。
3. 对方说话时确认“音频输入”有电平，观察原文和译文。翻译过程中可以直接在下拉框更换麦克风、扬声器或耳机，无须先暂停；课堂记录和云端会话保留。切换期间以静音包维持连接，设备初始化或首次授权可能造成短暂采音空档。切换失败会提示并暂停，选择可用设备后点击继续。等待切换时也可以点暂停或结束来取消。
4. 暂停和结束会释放本机采集；继续会重新连接所选设备。拔下耳机或切换会议输出后，请在下拉框选择会议实际使用的设备；若原设备断开已触发暂停，选好后点击继续。

**长时间安静可以继续保持开始状态。** 麦克风保持原有持续采样；扬声器 / 耳机没有声音输出时，本机服务也会每 80ms 发送一帧静音音频，恢复声音后继续传真实音频。云端的“8 秒等包超时”指没有收到音频包，不是要求每 8 秒说一句话；正常静音应显示“云端等待语音”，不需要重新开始。设备拔出、采集进程退出或网络异常仍会单独处理。页面“无输入”的零电平可以是正常安静，不等于会话断开。

**Windows：**使用共享模式 WASAPI 回环采集。新依赖由 `uv sync --locked` 安装，无需虚拟声卡。会读取所选输出端点的所有声道后再混成单声道，避免单声道 WASAPI 采集的已知问题。受保护的音频内容或部分专用设备不一定允许回环采集。

**macOS：**需要 **macOS 14.2 或更高版本**和 Apple Command Line Tools。若未安装工具链，在终端运行 `xcode-select --install`，按系统提示完成安装。第一次读取设备列表时会自动编译本项目的 Swift 音频组件到 `.local/system-audio/`；也可以预先运行 `uv run --locked python -m scripts.build_system_audio`。首次采集需允许“系统音频录制”；只使用 Core Audio 音频接口，不采集画面、不安装驱动、不修改系统默认输入或输出设备。系统若拒绝权限，请在隐私与安全性设置中允许音频采集程序或启动服务的宿主录制系统音频，然后重新开始。

想只检查采集，不上传云端时，可保持音乐播放并运行：

```sh
uv run --locked python -m scripts.check_system_audio --seconds 5
```

此诊断只打印设备名、采样数量和电平，不保存音频。网页点击开始则会将所选声音发送到火山引擎翻译；同一输出设备上的音乐和其他应用声音也会一起进入翻译。歌曲不等同会议语音测试，纯伴奏不一定产生字幕。

实现依据：[Apple Core Audio taps](https://developer.apple.com/documentation/CoreAudio/capturing-system-audio-with-core-audio-taps)和 [SoundCard 官方文档](https://github.com/bastibe/SoundCard)。Windows 路径已实现并有自动测试，尚待 Windows 实机验证；本次 Mac 已用真实耳机输出完成本地电平采集。

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
