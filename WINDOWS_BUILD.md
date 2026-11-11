# 在 Windows 电脑构建课堂同传 EXE

2026-11-11 源码更新：共享启动器已为 Windows 加入右上角“更换 API Key”按钮。输入新 Key 并保存后，程序自动停止旧服务，再使用新配置重启；刷新原课堂网页即可继续，已保存课程保留。下方主按钮为“开始课堂”和“退出课堂”。现有 `packaging/windows.spec` 直接打包此启动器，无需额外开关。

要获得上述功能，需要在 Windows x64 上使用本次源码重新构建并实机验证。下文 2026-11-10 的既有 EXE 发布记录早于该功能；旧 EXE 不会自动获得更新。本轮已完成 Mac 及共享逻辑测试，尚未重新生成或验证新的 Windows EXE。

2026-11-10 最新构建已完成：当前 `dist/windows/ClassroomInterpreter.exe` 和桌面 `青衿课堂同传-20261110.exe` 包含音频待命优化、普通固定字幕框及已确认的全屏布局。前端 100 项、后端 165 项、自检与 HTTP/设备枚举冒烟检查通过；本文下方“尚未封装”说明保留为此前开发阶段记录，以此条最新状态及 `tests/ACCEPTANCE.md` 为准。其他 Windows 硬件和安全软件组合仍需用最终 EXE 试装验证。

这份说明供另一台 Windows 电脑上的 Codex 接手使用。Mac 已准备启动入口、资源配置、Windows 音频子进程适配和构建脚本；真正的 Windows 可执行文件需在 Windows x64 上生成并验证。PyInstaller 不支持直接在 macOS 上构建 Windows EXE。

## 从 Mac 转到 Windows

1. 在 Mac 把本次源码、`uv.lock`、`desktop_launcher.py`、`packaging/`、`scripts/build_windows.py`、`build-windows.cmd` 和本说明一起提交并推送到原 GitHub 仓库。
2. Windows 上第一次使用时 clone 仓库；已有仓库则在保留本地改动的前提下 pull。
3. 将下面这段话交给 Windows 上的 Codex：

> 请阅读 WINDOWS_BUILD.md 和 AI_readme.md，按当前源码完成 Windows x64 单文件 EXE 构建。检查并安装构建机需要的 uv、Python 3.12 x64 和 Node.js LTS，使用锁文件安装依赖，运行构建脚本并修复实际出现的问题。验证打包后的自检、本机 HTTP 服务、首次配置、重复启动、退出及 Windows 音频采集。不要把本机 .env、真实 API Key 或用户数据打包进产物；云端付费调用与现场采音需沿用用户已有授权。报告最终 EXE 的绝对路径、自动检查结果和仍未验证的项目。

## 构建机准备

仅构建机需要开发工具，最终用户不需要安装 Python、Node.js、uv 或 SQLite。

- Windows 10/11 x64。
- [uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/)；uv 可自动取得 Python 3.12。不要复用从 Mac 拷来的 `.venv`。
- [Node.js LTS](https://nodejs.org/en/download)，包含 npm；用于构建前端。安装后重新打开终端，以便 PATH 生效。
- 构建机需能连接依赖下载源。

在项目根目录运行：

```powershell
uv run --locked --python 3.12 --group build python -m scripts.build_windows
```

工具已就绪时，也可以双击根目录的 `build-windows.cmd`。脚本会依次：

1. 按 `package-lock.json` 安装前端依赖，构建前端并执行前端测试。
2. 执行 Python 自动测试。
3. 使用 `packaging/windows.spec` 生成单文件程序。
4. 执行生成程序的 `--self-test` 和 `--smoke-test`：检查 SQLite/Tk/Windows 音频依赖、课程词表和页面资源，在临时数据库验证写入和重开读取，启动本机 HTTP 服务检查历史课程接口、通过 `/api/audio-outputs` 检查打包音频子进程的设备枚举及正常退出；不调用云端，不采集音频，也不写入用户真实课程库。

成功产物：

```text
dist/windows/ClassroomInterpreter.exe
```

打包中间文件在 `.local/pyinstaller-windows/`。产物和本地配置不提交到 Git；可另外通过文件传输分发 EXE。

## 最终用户使用

双击 EXE 后，首次会出现 API Key 输入窗口。填写用户自己的**豆包语音新版控制台 API Key**；不能使用火山方舟 `ark-` Key。该版本沿用本项目已实测的 `delta` 字幕语义。

配置保存在 `%LOCALAPPDATA%\ClassroomInterpreter\config.env`，不写进 EXE，也不放到临时解压目录。更换 EXE 时保留配置。需要更换 Key 时，先退出程序，编辑或删除该配置文件；删除后下次启动会重新提示填写。

启动器会自动开启仅监听 `127.0.0.1` 的本机服务，并用默认浏览器打开 `http://localhost:8765`。建议使用已有的 Chrome 或 Edge。用户仍在浏览器内点击“开始课程”并授予麦克风权限；右下角“字幕全屏”保留。首次填写凭证与授予权限是正常设置，不需要安装数据库或开发工具。翻译仍依赖网络和已开通的云端服务。

启动器窗口用于重新打开课堂界面和退出本机服务。关闭网页不会自动退出启动器；退出程序请使用启动器的“退出程序”。端口已被其他实例占用时会明确提示，不会终止其他进程。

课程文字自动写入 `%LOCALAPPDATA%\ClassroomInterpreter\records.sqlite3`，课程名称为 `YYYY-MM-DD-001`（本机日期、当天序号），暂停/继续/重连不重复编号。已收到的字幕快照在发送给页面前提交到数据库；关闭网页或重新启动后可在“历史课程”查看并导出同名 TXT。未定稿内容也保存并标注，不保存录音。保存失败会提示，未收到或尚未成功保存的文字无法保证恢复。

开发态记录在项目 `.local/records.sqlite3`，不提交到 Git。打包只能包含程序与预置词表，不得包含构建者的课程数据库及 SQLite 的 `-wal`、`-shm` 文件。数据库与 EXE 分开放置，更新 EXE 时保留用户记录。

## Windows 上的完成检查

2026-11-10 源码新增扬声器待命启动优化，尚未封装。`--audio-worker --list-and-wait` 枚举后只等待 stdin 命令，不录音；进程只使用一次，闲置 60s 回收。准备失败时本次运行关闭加速，保留普通枚举和冷启动；准备未完成只额外等最多 250ms。使用同一 EXE、相同依赖和 WASAPI 共享模式，不依赖构建机路径或固定设备名。

面向多台新 Windows 机器分发前，需用最终 EXE 在至少两类硬件上试装：检查无 Python/Node 环境、普通用户权限、中文及空格路径、内置/USB/蓝牙输出、休眠恢复和设备断开、准备过期及失败回退、关闭后无待命进程残留。当前只在本机验证了四个输出端点及源码回归；不能把本机通过视为全部 Windows 机器验收，也不能用旧 EXE 验证本次改动。Windows x64 是现有打包目标，ARM/32 位需单独评估。

- 构建脚本、自检与 HTTP 冒烟检查全部通过。
- 将 EXE 单独复制到另一目录运行，验证不依赖项目源码或构建目录；尽可能在未安装 Python/Node.js 的 Windows 电脑上复测。
- 首次配置和再次启动正常，不在 EXE 或日志中夹带构建者的凭证。
- 双击只打开一套服务，重复启动提示端口占用；退出后能立即重新启动。
- 麦克风授权、字幕全屏、暂停/继续、TXT 导出正常。
- 新开两节课程，检查日期序号依次增加；暂停/继续不另建记录。关闭网页并重启 EXE 后，从“历史课程”查看并导出，核对原文、译文和未定稿内容。替换 EXE 后配置与历史记录仍保留。
- 使用 `--audio-worker --list` 或界面检查真实扬声器/耳机枚举，验证所选设备的采集、停止和再次开始。自动测试与依赖导入不能代替 Windows 实机采音。
- 单文件 EXE 的音频子进程必须保留父进程已有的 `_PYI_ARCHIVE_FILE`、`_PYI_APPLICATION_HOME_DIR`、`_PYI_PARENT_PROCESS_LEVEL`、`_PYI_SPLASH_IPC`，复用当前解压目录；仍不继承云端凭证。若清空这些打包启动信息，设备查询会重新解压整个 EXE，可能超过超时而导致页面只有麦克风。枚举最多等待 30 秒，不应只用单独运行 worker 的成功结果代替 HTTP 接口检查。
- 真实翻译只在用户提供可用凭证、明确允许相应采音与调用时验证；不能把 HTTP 冒烟或模拟测试描述为真实字幕验收。

Mac 上的代码测试通过不等于以上 Windows 实机检查已经完成。接手 Codex 应在完成后记录实际结果。

参考：[PyInstaller 平台要求](https://pyinstaller.org/en/stable/)、[单文件打包原理](https://pyinstaller.org/en/stable/operating-mode.html)。


## 麦克风授权与界面

麦克风由浏览器通过 getUserMedia 授权，EXE 本身不绕过浏览器权限。在音频输入中选择麦克风并开始课程，按浏览器提示授权；选择扬声器回环时不需要浏览器麦克风权限。按用户要求，前端已移除麦克风检测、试音和原声模式入口，启动器不再展示试音说明。

无电平不一定是授权失败，也可能是所选设备静音或浏览器、驱动处理问题。请核对实际输入设备和 Windows 音频状态，不要仅据零电平推断权限问题。

启动器、首次 Key 设置和正式网页采用米白、浅木色与低饱和绿色，使用 `frontend/public/assets/` 中的学院原图衍生 PNG/ICO。PyInstaller 图标和 Tk 窗口图标一并设置；自检验证资源齐全。用户配置和课程库仍使用原数据目录。
