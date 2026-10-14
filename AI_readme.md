# AI 维护说明：课堂同传

本文件面向后续修改项目的 AI 和开发者。面向使用者的 macOS / Windows 安装、启动步骤在 [user_readme.md](user_readme.md)。修改前先读 [PLAN.md](PLAN.md) 的范围和 [tests/ACCEPTANCE.md](tests/ACCEPTANCE.md) 的实测边界；不要把未验收项目写成已通过。

## 项目速览

这是**本机网页 + 本机 Python 中继 + 火山引擎云端 AST S2T**，并非离线翻译或纯前端站点。普通使用先 `npm --prefix frontend run build`，再在根目录运行 `uv run --locked python -m backend`，打开 `http://localhost:8765`。`npm --prefix frontend run dev` 只启动 Vite 开发服务器；使用开发模式时还要另开终端运行 Python 后端，访问 `http://localhost:5173`。

数据流：浏览器 `getUserMedia` → `AudioWorklet` → 连续重采样为 16kHz PCM16 → 本机 `/ws/translate` → `backend.session.Session` → 官方 AST WSS / Protobuf → `backend.protocol.Normalizer` → 浏览器原文、译文与历史状态。云端只返回文字，不请求或播放合成语音。

| 位置 | 职责与修改入口 |
|---|---|
| `frontend/src/main.tsx`、`style.css` | 页面、控制动作、状态与提示；日常 UI 修改从这里开始 |
| `frontend/src/input.ts`、`capture.ts` | 优先电脑内置麦克风、手动设备选择、浏览器采集生命周期 |
| `frontend/src/worklet.ts`、`audio.ts` | 100ms 输入电平、44.1/48kHz 连续重采样、PCM16 与 40/80ms 分包 |
| `frontend/src/connection.ts`、`subtitles.ts` | 本机 WebSocket、心跳/重连、字幕增量/定稿与 epoch 隔离 |
| `backend/config.py`、`app.py` | `.env`、localhost 限制、健康检查、单连接、静态资源与本机 WS |
| `backend/session.py`、`protocol.py` | 云端会话、队列/退避/收尾、官方 Protobuf 请求和事件归并 |
| `protocol/protos/`、`backend/generated/` | 官方协议源码及生成绑定；来源/哈希在 `protocol/sources.json` |
| `scripts/probe.py`、`smoke_relay.py` | 真实云端协议探测与本机中继联调；会发送测试音频到云端 |
| `frontend/src/*.test.ts`、`tests/` | 自动回归；真实环境覆盖情况见 `tests/ACCEPTANCE.md` |

必须保持的约束：密钥只在根目录 `.env` 和 Python 进程中，绝不进入 `frontend/dist`、日志、测试夹具或聊天；`.env.example` 不含密钥。后端只监听 `127.0.0.1`，WebSocket 只接受明确的 localhost Origin，且只允许一条活跃本机会话。已发音频不重放；超限队列产生缺口提示，不伪装成完整字幕。浏览器字幕在内存，只有用户主动导出才保存 TXT。不要用模拟数据充当产品翻译结果。

当前官方接口已用真实短音频验证：`TaskRequest.source_audio.binary_data` 为无头 PCM；`Response` 是 **delta**，`End` 是完整段；`response_meta.Sequence` 是段 ID，多个 Response 会共享它，不能把它当全局消息序号去重。原文和译文分别定稿。`AudioMuted` 是云端暂未检测到语音，不能解释为电脑静音。改动协议、资源或模型版本时先重新真实探测，再决定 `.env` 中 `VOLC_SUBTITLE_RESPONSE_MODE`；样例故意保持 `unverified` 防止把未知版本直接投入使用。

改动后至少运行：

```sh
uv run --locked pytest -q
npm --prefix frontend test
npm --prefix frontend run build
```

前端改动必须重新构建并刷新 `localhost:8765` 页面；后端或 `.env` 改动必须重启 Python 服务。Windows 的从零安装步骤已写入用户指南，但目前只在 macOS 实机运行过；不要声称 Windows、长课、断网、延迟或账单验收已完成。

## 实现与操作细节

按 [PLAN.md](PLAN.md) 实现的 React + TypeScript + AudioWorklet / Python FastAPI 本机项目。默认中英反转（`zhen`），只显示文字，通过火山引擎 AST S2T 云端翻译；不是离线翻译。

**当前状态：本机源码、页面、官方 Protobuf 中继和自动测试已完成；使用官方公开短音频完成真实 AST S2T `zhen` + 无头 PCM + 80/40ms 包验证。80ms 会话返回 8 段原文及译文定稿，译文中间 Response 为增量片段。再经本机 `/ws/translate` 完整链路复测，得到 76 次译文中间更新、8 段译文定稿、8 段原文定稿，未发生错误或音频缺口。用户已在本机网页用真实麦克风短句试用，确认“暂停→继续”与“教室 · 远距离”模式都有输入电平和译文。当前 `.env` 已设置经样本核对的 `delta` 模式。家用 Wi-Fi、45–120 分钟和质量/延迟统计仍待验收。**

## 安装、构建与启动

需要 Python 3.11+、Node.js 20.19+（建议 22/24）、npm，以及 [uv](https://docs.astral.sh/uv/)。请在项目根目录执行：

```sh
uv sync --locked
npm --prefix frontend ci
npm --prefix frontend run build
test -f .env || cp .env.example .env
```

在本机编辑 `.env` 的 `VOLC_API_KEY`，使用[豆包语音新版控制台的 API Key](https://console.volcengine.com/speech/new/setting/apikeys?projectName=default)。火山方舟的 `ark-` Key 对此接口返回 HTTP 401；豆包语音 Key 还需在同一项目开通同声传译2.0服务；不要把凭证发到聊天或写进前端。未配置时页面和健康检查会明确提示。依赖分别锁定在 `uv.lock` 和 `frontend/package-lock.json`。

服务启动命令：

```sh
uv run --locked python -m backend
```

打开 **http://localhost:8765**。只监听 `127.0.0.1`，不开放局域网；浏览器 `localhost` 可请求麦克风。不要改成普通 HTTP 的局域网 IP。停止服务用 Ctrl+C。修改配置后重启服务；修改前端后重新构建并刷新。

本项目已在当前工作区安装依赖并构建，也可以直接运行 `.venv/bin/python -m backend`。

开发时使用两个终端：

```sh
uv run --locked python -m backend
```

```sh
npm --prefix frontend run dev
```

打开 http://localhost:5173，Vite 将 `/api` 和 `/ws` 代理到本机服务。

## 真实接口探测与复核

准备一段 **不超过 60 秒、16kHz / 单声道 / 16-bit WAV** 的非敏感测试音频，例如明确朗读的中英测试句。脚本会将该录音发送到火山引擎，可能产生云端费用。没有凭证时不会连接。

```sh
uv run python -m scripts.probe short-test.wav --container pcm --show-text --save-redacted
```

默认 80ms；可以用 `--packet-ms 40` 对照。方向支持 `--mode auto`、`zh-en`、`en-zh`。已用官方 Demo 附带的短 WAV 验证 `--container pcm` 成功；`--container wav` 仅供协议对照。浏览器生产链路使用无头 PCM。

检查同一段多个 Response：如果每次是新片段则为 `delta`，如果是该段截至当前的完整文本则为 `snapshot`；同时确认 End 提供完整段、原文/译文事件、时间戳、末句收尾、计量与没有音频输出。`--show-text` 仅显式打印短测试音频文本；服务本身不记录课程文本。`--save-redacted` 保存字符替换后的样本到忽略目录 `.local/`，保留前缀/相等关系，不保存原始音频或原始文本。

本次真实样本已确认 **PCM 分支、S2T、zhen 和增量字幕**，当前 `.env` 已设置：

```dotenv
VOLC_SUBTITLE_RESPONSE_MODE=delta
# 重新接入其他协议版本时先复测，不要猜测。
```

重启服务再开始课程。详细字段差异、附件来源和校验见 [protocol/README.md](protocol/README.md)。长时间稳定性仍需独立验收。

## 页面行为

- 点击“开始课程”后申请麦克风，等待上游 SessionStarted 才开始采集上传。麦克风默认“电脑内置优先 · 自动”：优先识别 Mac/Windows 内置输入，仍可从下拉框手动选择 iPhone、USB 等设备；页面显示实际使用的输入源。首次授权前浏览器可能隐藏设备名称，获准后会重新识别，再上传音频。若无法识别内置设备或只能使用系统默认，会提示核对输入源。自动翻译模式中英逐语种反转；混合输入可以输出混合译文。方向/设备/收音方式/包长在暂停后切换，继续时新建会话。
- “云端等待语音”表示上游暂未判定出语音，麦克风仍在采集；它不表示电脑静音。麦克风输入条按近 100ms 的完整窗口统计，并用 dBFS 显示弱信号。远距离课堂可选“教室 · 远距离”，关闭浏览器降噪与回声消除，保留自动增益；环境噪声也可能更明显。更可靠的做法是在授课位置使用近距离外接麦克风。
- 80ms 为默认，40ms 是实验选项。实际采样率经连续低通 FIR 和重采样转换为 16kHz PCM16，小端二进制传输；自然停顿仍传真实静音。
- 译文中间结果直接显示，原文独立更新；分别定稿归档，不等待配对。字号 28–80px，支持全屏、原文开关；向上滚动停止跟随，点击“回到最新”恢复。
- 暂停停止采集并释放麦克风，结束上游。继续保留历史并增加会话 epoch。结束先上传最后短包，发送 FinishSession，最多等 5 秒；未完成段显示“未定稿”。
- 常亮失败不会阻断翻译；前台恢复会按运行状态重新申请。设备中断提示重新选择并继续；AudioContext 暂停时尝试恢复。系统锁屏/休眠或后台冻结时不能保证持续采音。
- 历史只存在当前页面内存，不写入浏览器存储；默认不保存音频或课程文本。TXT 需用户主动导出。刷新结束会话并清空记录，运行中有离开提示。
- 本机连接每 10 秒应用心跳、30 秒无确认重连；云端网络失败按 0.5/1/2/4/8/最大10秒加抖动重试。明确鉴权、参数、额度及未知业务错误停止重试并提示检查；不会回放已发送音频。
- 浏览器待发数据最多 16KB（0.5 秒），中继队列最多 48KB（1.5 秒），另有一个正在发送的包和底层网络缓冲。超过限制丢弃未发送旧音频或重建连接，并提示缺口；断网不能保证不漏内容。
- 仅允许明确的 localhost/127.0.0.1 Origin，限制一条活跃本机连接、控制帧/音频帧大小和上传速率。重复开始不会创建并行收费会话。云端 WSS，密钥只在服务端。

## 验证

```sh
uv run --locked pytest -q
npm --prefix frontend test
npm --prefix frontend run build
```

实际测试与未验证项目见 [tests/ACCEPTANCE.md](tests/ACCEPTANCE.md)。覆盖 44.1/48kHz 的时长、跨块连续性和带外抑制，PCM 编码、分包、短尾，独立字幕、幂等定稿、旧会话拒绝，心跳、暂停取消重试、结束后不上传、错误分类与队列上限。协议单测含官方生成类型构造的消息，另有来自真实云端、文本字符替换后的事件样本；本机中继也已用官方短音频完成真实联调。

本机接口：`GET /api/health` 返回凭证布尔状态、协议/语义就绪状态，不返回密钥；`WS /ws/translate` 控制/字幕为 JSON，音频为二进制。正式前端由同一 FastAPI 服务提供。

## 排错与已知限制

- 系统自带 Python 可能是 3.9，使用 `uv` 的 Python 3.11+；本次验证使用 3.12。当前系统配置了 SOCKS 代理，已包含 `python-socks[asyncio]` 依赖。
- `credentialsConfigured=false`：检查 `.env` 与启动目录，重启。`subtitleSemanticsVerified=false`：先完成上面的协议探测，不能跳过实测。
- 401/403 或业务错误：首先核对是否误用火山方舟 `ark-` Key；必须在豆包语音新版控制台获取。`requested resource not granted` 表示 Key 所属项目还没有同声传译2.0授权，打开控制台“开通管理”查看。开通弹窗显示默认按 Token 后付费，需由账号持有人阅读并同意条款。再核对 API Key、`volc.service_type.10053` 开通、余额/额度与参数。不要混用旧 App ID / Access Token，也不要把 `doubao-simul-s2s` 当 URL/资源 ID。页面不展示未脱敏的云端错误全文。
- 浏览器权限拒绝：在 localhost 的站点设置中允许麦克风，检查系统权限，重新点击开始。没有设备标签时先授权再刷新设备列表。
- 端口占用：停止已有服务，或修改 `.env` 的 PORT。开发代理默认 8765，改端口需同步 `vite.config.ts`。
- 8765 页面提示先构建：执行 `npm --prefix frontend run build` 后重启服务。多开标签页只允许一个活跃连接。
- 常亮失败：检查浏览器支持及节电设置。后台冻结或锁屏不会保证可靠上传。
- 网络抖动：检查实际授课位置 Wi-Fi 的上传稳定性，而非套餐下载速度；PCM 有效载荷约 0.256Mbps。缺口提示意味着内容可能漏译。
- 不承诺稳定低于 1 秒；官方介绍的低延迟约 2–3 秒，首次可用译文 P50≤3秒/P95≤5秒是待验证目标，40ms 包只减少音频累积时间。
- 不包含系统音频、会议音频、手机锁屏、学生端、账号、课后总结、语音合成或回放。最长会话、等包/长静音限制及计量累计语义待确认，不编造固定时限。
- 真实课堂质量、45/90/120 分钟、120 分钟至少 3 次、断网/长静音、设备异常、常亮与账单核对尚未进行；短句麦克风与公开音频成功不代表长课已验收。
