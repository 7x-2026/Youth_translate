# 在 Windows 电脑构建课堂同传 EXE

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
4. 执行生成程序的 `--self-test` 和 `--smoke-test`：检查 SQLite/Tk/Windows 音频依赖、课程词表和页面资源，在临时数据库验证写入和重开读取，启动本机 HTTP 服务检查历史课程接口与正常退出；不调用云端，不采集音频，也不写入用户真实课程库。

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

- 构建脚本、自检与 HTTP 冒烟检查全部通过。
- 将 EXE 单独复制到另一目录运行，验证不依赖项目源码或构建目录；尽可能在未安装 Python/Node.js 的 Windows 电脑上复测。
- 首次配置和再次启动正常，不在 EXE 或日志中夹带构建者的凭证。
- 双击只打开一套服务，重复启动提示端口占用；退出后能立即重新启动。
- 麦克风授权、字幕全屏、暂停/继续、TXT 导出正常。
- 新开两节课程，检查日期序号依次增加；暂停/继续不另建记录。关闭网页并重启 EXE 后，从“历史课程”查看并导出，核对原文、译文和未定稿内容。替换 EXE 后配置与历史记录仍保留。
- 使用 `--audio-worker --list` 或界面检查真实扬声器/耳机枚举，验证所选设备的采集、停止和再次开始。自动测试与依赖导入不能代替 Windows 实机采音。
- 真实翻译只在用户提供可用凭证、明确允许相应采音与调用时验证；不能把 HTTP 冒烟或模拟测试描述为真实字幕验收。

Mac 上的代码测试通过不等于以上 Windows 实机检查已经完成。接手 Codex 应在完成后记录实际结果。

参考：[PyInstaller 平台要求](https://pyinstaller.org/en/stable/)、[单文件打包原理](https://pyinstaller.org/en/stable/operating-mode.html)。


## 麦克风授权、试音与原声模式

麦克风由浏览器通过 getUserMedia 授权，EXE 本身不绕过浏览器权限。在课程未运行时点击“授权并试音”，浏览器尚未授权时选择允许；已授权时不会重复弹窗。试音使用相同的麦克风/AudioWorklet 采集链路，只在本机显示 10 秒电平，不建立翻译 WebSocket、不上传、不保存。试音期间禁用开始课程与设备选择，停止、离开页面或结束试音后释放设备。取消授权等待后，迟到的授权结果也会释放。

若 Windows 输入电平正常、网页已授权但无电平，暂停课程后开启“麦克风原声模式”再试音；该选项关闭浏览器回声消除与降噪，默认关闭以保留原有处理。成功后同一设置用于开始课程与运行中切换麦克风；扬声器系统音频采集不受影响。无电平不是授权失败的充分证据，也可能是所选设备静音或浏览器/驱动处理问题。

启动器与首次 Key 设置采用浅色竖版布局（暖白背景、白色卡片、深绿按钮）。授权与试音说明展示在启动窗口；已有用户 Key 与课程数据库不迁移、不覆盖。
