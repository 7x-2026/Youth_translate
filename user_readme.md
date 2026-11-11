# 课堂同传使用指南（macOS / Windows）

Mac 现可使用独立应用：完整功能要求 macOS 14.2+，按 Apple 芯片 / Intel 选择对应安装包。安装后无需 Python、Node.js 或编译工具，首次填写自己的 API Key 即可。安装步骤、数据目录与签名说明见 [macOS 应用指南](MACOS_BUILD.md)；下文终端命令继续适用于源码版。

Mac 0.1.1 启动器右上角新增小按钮“更换 API Key”：输入新 Key 后点“保存并应用”，本机服务自动重启，刷新课堂网页即可继续。当前翻译会中断，历史课程保留；取消不修改原 Key。下方保留“开始课堂”和“退出课堂”，点击“退出课堂”关闭服务，只关网页仍会保留后台。

2026-11-10 已重新封装 Windows x64 单文件版，包含下面的音频启动准备、固定字幕框和已确认的全屏滚动布局。默认选择“自动中英互译”，在同一会话中由模型按中文/英文输入进行反向翻译，无须手动切换；字幕流式更新，仍有识别和网络延迟。三种设计方案仅为示意，没有应用到本次发布。

Windows 扬声器启动准备：设备列表读取完成后，组件最多待命 60 秒，点击开始时才采集。准备有效时可减少重复启动等待；过期或准备失败仍使用原有启动方式，所以首次加载、立即继续或等待较久后开始仍可能较慢。暂停和退出仍释放实际采集；界面不增加设置。

普通页面的字幕框固定预留三行大字号译文、两行较小字号原文，不随句子长短跳动；超出部分可在对应文字区域内滚动查看。新句从开头显示。手动调整字号时，预留高度跟随字号变化；字幕全屏继续使用原有滚动布局。

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

7. 用 Chrome 或 Edge 打开 **http://localhost:8765**，点击“开始课程”，允许浏览器和系统使用麦克风。默认优先电脑内置麦克风；也能从“音频输入”下拉框选 iPhone 或外接设备。页面统一使用豆包标准同传、标准近讲收音和 80ms 音频包。会议声音的使用方法见下文。结束时点击网页“结束”，再在终端按 `Ctrl+C` 关闭本机服务。

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

然后打开 **http://localhost:8765**。如果网页已经能打开，就说明服务可能已在运行，**不必再启动第二个**。更换 `.env` 后重启服务；代码更新后重新执行对应系统的 `uv sync --locked --python 3.12`、`npm --prefix frontend ci`、`npm --prefix frontend run build`，并重启后台以加载新功能。课程文字会自动保存到本机，关闭页面或重启后仍可在“历史课程”查看并导出 TXT。

## 课程自动保存与导出

点击开始后自动创建课程记录，名称如 `2026-11-07-001`、`2026-11-07-002`，每天从 001 开始。暂停、继续或断线重连沿用同一条记录；新开始一节课才分配新名称。字幕显示“已自动保存到本机”时，已收到的原文和译文已经写入数据库。正在变化的文字也会保存，未定稿时明确标注；云端尚未返回的末句无法恢复。

下方“历史课程”列出已保存记录，点击“查看”阅读，点击“导出 TXT”下载。无需先开始翻译、配置云端或保持上次页面打开；当前课程旁的导出按钮仍可直接导出页面文字。导出文件名使用课程日期和序号，包含原文、译文、时间及未定稿标记。

源码运行时数据库在项目 `.local/records.sqlite3`；Windows EXE 运行时在 `%LOCALAPPDATA%\ClassroomInterpreter\records.sqlite3`。数据库不会上传 GitHub，也不会随替换 EXE 被清除。不需要安装 SQLite，不保存录音。若页面提示保存失败，请先保持页面并导出当前 TXT，再检查磁盘空间和权限；历史数据库可能缺少失败期间的内容。

点击“开始课程”后，音频设备准备与翻译连接准备会并行进行，页面立即显示启动进度；设备就绪后才开始上传音频。首次系统授权可能仍需等待，首次字幕还取决于讲话内容和云端响应。

## 如何确认复现成功

1. **不连接云端的检查**：在项目根目录运行 `uv run --locked pytest -q`、`npm --prefix frontend test`、`npm --prefix frontend run build`。这些检查不需要 Key；它们不能代替真实麦克风联调。
2. **页面检查**：启动后访问 `http://localhost:8765/api/health`，应看到 `"ready":true`；再打开 `http://localhost:8765`，确认页面可显示。`ready` 只表示本机配置齐全，不代表云端已接受该 Key。若为 `false`，先检查 `.env`、Key 类型和字幕模式。
3. **真实翻译检查**：在网页点击“开始课程”，允许麦克风，朗读一句不含隐私的中文或英文测试句。页面应出现输入电平、原文和译文；结束后再检查最后一句是否定稿。只有这一步通过，才能说明此电脑的麦克风、网络、Key 和云端资源已一起接通。

若要复现协议探测，而非只试用网页，需**自己准备**不超过 60 秒的 16kHz、单声道、16-bit WAV 测试音频；仓库没有附带原始录音。把文件放在项目根目录并命名为 `test.wav` 后运行 `uv run --locked python -m scripts.probe test.wav --container pcm`。这会把测试音频发送至火山引擎，可能产生费用。不同录音的字幕段数和延迟不会与 [验证记录](tests/ACCEPTANCE.md) 中的历史样本相同。

## 开会时翻译耳机 / 扬声器里的声音

当前版本使用学院 logo 和米白、浅绿色界面，已移除麦克风检测/试音入口。选择麦克风后直接开始课程并按提示授权即可。实时记录区域显示最近 200 条，完整文字仍可通过导出和历史课程查看；系统音频采集期间会暂时禁用译文播报，避免播报声再次进入翻译。

源码待封装更新：当前译文在快速切句时会短暂停留，同一句的文字修正仍即时显示；为保持实时，新句额外等待最多约 1 秒。多句集中到达时优先显示最新候选，完整内容仍即时进入记录与导出。暂停或结束会显示最新已收到的结果，不在停止后继续轮播旧句。学院 logo 素材已更新为透明底；这些后续修改将在需求确认后统一封装。

全屏译文现为一个类似歌词的滚动窗口，当前句突出显示，历史句向上淡化；不再分“上一句/当前句”两个区域。文字自然排满后再滚动，最新句下方只留约一行半，减少居中造成的留白。下方原文区域缩小约三分之一，给译文留出更多空间。此项只调整全屏显示，普通页面和完整记录不受影响。

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
- **声音离电脑较远？** 将电脑或外接麦克风放到讲话者附近。网页输入电平显示的是数字音频电平，不代表云端一定能识别每句话。

开发与协议维护说明见 [AI_readme.md](AI_readme.md)。

## 可选方言模式（实验性，需单独开通服务）

当前前端统一使用豆包同传，已移除识别服务选择。以下是保留的实验性方言后端配置，供开发调试使用；配置凭证不会让页面切换至方言模式。后端入口为 `/ws/translate?engine=dialect`。模型自动处理普通话和支持的口音/方言，不需要选择河南话、湖北话等地区。

此模式使用腾讯云 ASR `16k_zh_en` 接收音频并实时转写，每句定稿后交给 TokenHub `hy-mt2-lite` 翻译。不使用仅支持短时输入的 Preview ASR。河南话、湖北话列在 ASR 官方支持范围内，但不代表鄂西北各地口音已验收，需用实际讲话样本核对。自动中英方向按整句是否包含汉字决定目标语言，混合语句会整句翻译，与豆包同传逐语种反转的行为不同。

### 配置

1. 开通腾讯云实时语音识别，确认账号可用 `16k_zh_en`，取得账号 AppID 与具有所需权限的 SecretId、SecretKey。
2. 开通中国大陆广州地域 TokenHub 的 `hy-mt2-lite`，取得其 API Key。**现有豆包 API Key 不能代替这些凭证。** TokenHub Key 使用按量 API 的凭证，不是 Token Plan 专属地址的 Key。
3. 在本机现有 `.env` 中手动追加以下配置，不要替换原有豆包配置，也不要将真实值提交到 GitHub：

```dotenv
TENCENT_ASR_APP_ID=你的腾讯云账号AppID
TENCENT_SECRET_ID=你的SecretId
TENCENT_SECRET_KEY=你的SecretKey
TOKENHUB_API_KEY=你的TokenHub按量APIKey
```

也可设置同名进程环境变量。程序不会自动修改 `.env`。缺少配置时，方言后端会拒绝启动，不会偷偷回退或同时启动两家收费会话。`/api/health` 只返回配置是否齐备，不验证账户已开通、余额或实际调用权限。

4. 构建前端并重启后台，然后刷新页面：

```sh
npm --prefix frontend run build
uv run --locked python -m backend
```

后台若已运行，先在其终端 Ctrl+C 停止再重启，不要启动第二份。

### 行为与验证边界

- 本机麦克风与系统音频的采集实现不变；方言模式将所选音频发送至腾讯云 ASR，识别文本发送至 TokenHub，分别产生相应服务用量。
- 原文边说边显示，译文在分句后返回，因此时延与原有豆包同传不同；尚未测得真实课堂的准确率和延迟。
- 翻译任务串行处理，最多保留 4 个待译句，积压会明确提示缺口；不无限缓存音频或文本。单句超过 2000 字会停止并提示，不默默截断。
- 暂停会取消待处理任务；已经发送的文本翻译 HTTP 请求可能在服务端继续完成计费，但不会在页面迟到显示。结束最多等待既有的 5 秒，超时会提示收尾未完成。
- 原有 Origin、单会话、心跳与音频队列限制仍然生效。前端不保存腾讯云密钥；不增加 Python 依赖，不保存音频；课程文字按通用自动保存机制写入本机数据库。
- 自动测试使用隔离的服务替身。未配置新服务凭证、未完成真实云端/地区口音验收之前，只能确认适配代码与自动测试通过，不能宣称方言识别效果已验证。

接口资料（核对日期：2026-10-31）：[腾讯云实时 ASR](https://cloud.tencent.com/document/api/1093/48982)、[TokenHub 混元翻译调用](https://cloud.tencent.cn/document/product/1823/132252)。不采用已公告不再支持新用户的旧 TMT TextTranslate 接口。
