# 官方协议来源与差异

获取日期：2026-10-14。定义来自[火山引擎同声传译文档](https://www.volcengine.com/docs/6561/1756902)中的官方 Python Client 附件，原始 `.proto` 未修改。

- [proto 附件](https://p9-arcosite.byteimg.com/tos-cn-i-goo7wpa0wc/6493ecf3887246e3a99968961f716499~tplv-goo7wpa0wc-image.image)
- [Python Demo 附件](https://p9-arcosite.byteimg.com/tos-cn-i-goo7wpa0wc/f5a5a20f3ae441a49195c2b192c2cf93~tplv-goo7wpa0wc-image.image)
- 文件与附件 SHA-256 见 `sources.json`。Python Demo 中附带的定义作为本项目生成源；另行下载的 proto 包仅用于来源交叉核对。

生成：安装开发依赖后，在根目录运行 `uv run python scripts/generate_protocol.py`。生成器仅调整 Python import 为 `backend.generated` 包内引用，不改变字段、枚举、序列化或 proto 定义。生成文件已经提交在源码中，常规启动不需要 protoc。

已核对的差异：

1. Protobuf 消息类实际叫 `TranslateRequest` / `TranslateResponse`；`TaskRequest` 是事件枚举，不是消息类。
2. `source_audio.data` 实际为 **string**；二进制音频必须使用 **`source_audio.binary_data`**。`request_meta.SessionID` 和 `response_meta.StatusCode` 等字段使用 PascalCase。
3. 官方 Demo 采用旧版 App Key / Access Key，并设置 S2S。本项目仅根据最新接口文档使用 `X-Api-Key` + `X-Api-Resource-Id`，设置 `request.mode=s2t`，不设置 `target_audio`。
4. Demo 直接读取整个 WAV 文件并分块发送，文件头只发送一次。接口文档允许 wav/pcm。本项目启动字段维持 `wav/raw`，实时上传使用无文件头 PCM；**已用官方公开短音频真实联调成功**。探测脚本同时支持 `--container pcm` 和 `--container wav`（后者将测试文件的原始头发送一次）。真实样本已证实此无头 PCM 分支可工作；不要给每个包添加 WAV 头。
5. Demo 只是将收到的 `text` 放入列表，未演示实时字幕归并；不能由此确定 Response 的增量/快照语义。配置样例默认 `unverified`，阻止未经验证的生产会话。2026-10-14 使用官方公开短音频完成真实探测：原文和译文共 16 段，所有 Response 逐段拼接都与对应 End 完全一致，因此当前 `.env` 设为 `delta`。End 是完整段文本。脱敏事件见 `tests/fixtures/ast_real_redacted.json`。
6. 真实响应的 `response_meta.Sequence` 在同一段的多个 Response 中重复，按段递增；它不能用于按帧去重。本项目分别依据 source/translation 的 Start/End 生命周期及 Sequence 生成段 ID，不强行一对一配对。事件丢失、无序、跨段重叠的实际行为仍需更多场景验证。
7. 时间戳以官方毫秒值保留，不擅自解释为课程绝对时间；历史排序采用收到事件的时间。计量仅展示并保留最新上游报告，不假定报告是增量或累积。
8. 官方 Demo 设置 `ping_interval=None`，本项目沿用；不虚构云端业务心跳。网络发送有超时并会重建会话。最长会话、静音/等包实际限制仍待供应商及 120 分钟测试确认。

测试同时包含官方类型构造的合成消息及真实云端事件的字符替换样本；后者不包含 API Key、音频或原始字幕文本。
