# macOS 应用构建与使用

保留现有网页、自动中英互译、麦克风与系统音频输入、暂停继续、字幕全屏、术语表、课程保存及 TXT 导出。启动器内置 Python、前端和 Swift 音频组件，使用者不需要安装 Python、Node.js、uv 或 Apple Command Line Tools。

## 安装与使用

完整功能要求 **macOS 14.2 或更新版本**，这是现有 Core Audio tap 内部音频采集的系统要求。

- Apple 芯片（M 系列）：使用 `ClassroomInterpreter-macOS-arm64-0.1.3.dmg`。
- Intel 芯片：使用 `ClassroomInterpreter-macOS-x86_64-0.1.3.dmg`。

0.1.3 的 Intel 与 Apple 芯片版均新增右上角专业词汇管理和 Excel 词表导入：可搜索已有术语、单条新增、解析 XLSX/CSV/JSON 并预览后加入同一份完整词表，重复和冲突不覆盖。也包含最新全屏字幕调整：最新译文靠下显示、原文区域按内容收缩、行间留白与段落间距缩至此前的 2/3，左右字距使用默认值。分别适用于对应芯片的 Mac 和 macOS 14.2+，包括 macOS 15.4.1。

2026-11-19 按用户要求清理后，`dist/` 只保留上述两个 0.1.3 DMG。旧版、ZIP 和打包中间产物已删除；自检记录及原始校验文件已归档至 `.local/release-verification-0.1.3/{macos-arm64,macos-x86_64}/`。下文应用和 ZIP 路径为重新构建时生成的产物。

打开 DMG，将 `ClassroomInterpreter.app` 拖入 `Applications`，再从“应用程序”打开。首次填写使用者自己的豆包语音新版 API Key，之后自动在默认浏览器打开 `http://localhost:8765`。建议使用 Chrome 或 Edge；麦克风在浏览器内授权，内部音频按系统提示允许“系统音频录制”。启动器下方保留“开始课堂”和“退出课堂”；结束使用时点击“退出课堂”关闭本机服务。

**更换 Key**：点击启动器右上角的小按钮“更换 API Key”，输入新 Key 后点击“保存并应用”。程序自动停止旧服务并以新 Key 重启；刷新课堂网页后继续使用，不需要编辑配置文件或重开应用。当前翻译会中断，历史课程保留。点击“取消”不修改 Key；保存失败时保留原配置。此步骤只做输入格式校验，不代表已验证 Key 的云端权限或额度。

0.1.1 还在 macOS 使用可复用的本机监听地址，允许正常退出后快速重新打开；已有实例仍会阻止重复启动。升级前先退出旧版应用，再用新版替换“应用程序”中的应用；配置与历史课程沿用原目录。

当前产物使用本地签名，未完成 Apple Developer ID 签名及公证。从互联网下载后如果被系统拦截，确认文件来源，再在“系统设置 → 隐私与安全性”中选择“仍要打开”。无需关闭 Gatekeeper 或 SIP。[Apple 分发说明](https://developer.apple.com/developer-id/)

配置、课程数据库和首次保存后的完整词表分别存于：

```text
~/Library/Application Support/ClassroomInterpreter/config.env
~/Library/Application Support/ClassroomInterpreter/records.sqlite3
~/Library/Application Support/ClassroomInterpreter/terminology.json
```

更新或移动应用不影响应用版配置、历史课程及已保存的完整词表。源码版仍使用项目 `.env` 与 `.local/records.sqlite3`；应用不会自动复制开发者的 Key 或历史课程。若需保留已有课程，可先退出源码服务和应用，将源码版 `records.sqlite3` 连同存在的 `-wal`、`-shm` 文件备份后迁入应用数据目录；目标已有课程时不要覆盖，先分别导出所需 TXT。

## 构建机

需要 macOS、Python 3.12、uv、Node.js/npm 和 Apple Command Line Tools。构建依赖由 `uv.lock` 固定，前端由 `frontend/package-lock.json` 固定。默认根据 Python 的架构生成对应应用；Apple 芯片与 Intel 各自打包，[PyInstaller 架构说明](https://pyinstaller.org/en/stable/feature-notes.html#macos-multi-arch-support)。

```sh
uv run --locked --python 3.12 --group build python -m scripts.build_macos
```

也可双击 `build-macos.command`。脚本安装和构建前端、运行前后端测试，按 macOS 14.2 目标编译音频组件，打包 `.app` 并本地签名，验证资源白名单、架构、签名和脱离项目目录后的运行，再生成 DMG、ZIP 与 SHA256 校验文件。

```text
dist/macos-arm64/ClassroomInterpreter.app
dist/macos-arm64/ClassroomInterpreter-macOS-arm64-0.1.3.dmg
dist/macos-x86_64/ClassroomInterpreter.app
dist/macos-x86_64/ClassroomInterpreter-macOS-x86_64-0.1.3.dmg
```

`--skip-checks` 只适合已在相同源码运行完整测试后，为第二种架构复用现有前端；两种架构仍分别执行打包自检和设备枚举冒烟检查。在 Apple 芯片上借助已安装的 Rosetta 构建 Intel 版，可先安装 x86_64 Python，再用独立虚拟环境同步依赖：

```sh
UV_CACHE_DIR=.local/uv-cache uv python install cpython-3.12-macos-x86_64-none --install-dir .local/python --no-bin
UV_CACHE_DIR=.local/uv-cache UV_PROJECT_ENVIRONMENT=.local/venv-macos-x86_64 uv sync --locked --group build --python .local/python/cpython-3.12.15-macos-x86_64-none/bin/python3.12 --python-platform x86_64-apple-darwin
.local/venv-macos-x86_64/bin/python -m scripts.build_macos --skip-checks
```

上例 Python 路径应以实际下载版本为准。Rosetta 运行不等于 Intel 实机验收。构建过程不会上传应用、自动公证或调用翻译云端；分发时同时提供正确架构的 DMG 和 `SHA256SUMS.txt`。

## 自动检查的边界

`--self-test` 检查前端、词表、Tk、SQLite 持久化和已嵌入的音频组件。`--smoke-test` 在临时数据库与临时端口启动服务，检查健康接口、课程接口、页面资源、完整词表读取、真实 XLSX 解析/确认导入/临时词表保存和真实音频设备枚举；不打开录音，不建立翻译云端会话。构建脚本将应用复制到含中文和空格的独立目录，在过滤云端凭证的环境中执行两项检查。

新 Mac 的权限弹窗、macOS 14.2 最低版本、不同硬件/蓝牙设备及真实会议长时间翻译仍需实机验证。自动测试和 Rosetta 运行不能替代这些检查。
