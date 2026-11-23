# VoiceStudio 中文 AI 配音与音乐工作站（个人 Fork）

> 仓库：lv5accelerator-xy/VoiceStudio
> 上游：debpalash/VoiceStudio
> 状态：P0 工程准备与方案；以下均为计划和验收标准，不代表已在用户 Windows 设备安装成功。

## 目标与边界

本仓库是 VoiceStudio 的个人 Fork。保留官方 Electron + FastAPI 本地优先架构，为中文配音、游戏 NPC 台词、短视频旁白、Suno 音乐与 AI MV 后期提供可复用工作流。

- **VoiceStudio 负责**：中文 TTS、经授权的声线/声音克隆、故事旁白、语音转写、视频配音及本地 API/MCP。
- **Codex 负责**：安装、配置、调用 API、组织任务、质量检查、批量导出与测试。
- **Suno 负责**：歌曲/伴奏创作。不要把 VoiceStudio 的 TTS 等同于歌唱合成。
- **混音/剪辑负责**：将配音与音乐、音效做独立分轨、响度控制、视频剪辑和导出。

现有源码已包含简体中文 README、Electron i18n 词条、VoiceStudio Agent Skill。先审计/复用，不重复造轮子或改写全部界面。

## 架构

~~~text
Codex / 故事、歌词、旁白脚本、角色表
                  |
         VoiceStudio (Electron)
                  |
       本机 FastAPI (默认 :3900)
             |          |
          REST API      MCP
             |
      WAV / 字幕 / 任务清单
             |
    [Suno 音乐] + [音效资源]
             |
      分轨混音与视频剪辑
             |
        MV / 解说 / NPC 语音
~~~

所有音频源文件、模型权重、授权证明、密钥、个人语音样本均保存在用户本机受控目录，不提交到 GitHub。GitHub 存代码、文档、测试与无敏感信息的配置样例，不是本机语音推理服务器。

## 里程碑

| 阶段 | 交付内容 | 验收门禁 |
|---|---|---|
| P0 | Fork 基线、Windows 安装指南、Codex 施工指令、只读诊断脚本 | 能确认源码版本与上游约束；不改动主分支 |
| P1 | Windows 安装及本地后端连通 | App 启动；/health 成功；/openapi.json 可访问；记录真实 CPU/GPU |
| P2 | 中文 TTS 冒烟测试 | 用户主动选择模型并明确许可；成功产生可播放 WAV、记录时长与模型 |
| P3 | 角色配音批处理 MVP | 输入角色台词清单；生成可追溯音频、失败重试和 manifest；无重复覆盖 |
| P4 | Suno 音乐 + 旁白 + 音效导出 | 原始音轨独立保留；生成可复现的混音/剪辑工程 |
| P5 | 可选 GitHub Actions Windows 构建 | 独立无签名测试产物；CI 通过；确认许可与发布配置后再考虑 Release |

一阶段只允许 P0-P2，禁止未经验证就改造整个 Electron 产品。

## 本地 Windows 安装原则

1. 阅读官方 [Windows 文档](../install/windows.md)、[Agent 安装规范](../install/agent.md)、[Electron 开发说明](../../electron/README.md) 和 [Skill](../../skills/voicestudio/SKILL.md)。
2. 推荐先从**官方 Releases** 安装稳定版验证用户机器是否能运行；Fork 源码开发再使用 Bun。Electron 是当前受维护桌面端；不要启动或复活归档的 Tauri。
3. 对 Windows x64，预留至少约 10 GB 空间（实际依模型数量变化）。如需要，将引擎环境设置在较大的非系统盘，例如设置环境变量 OMNIVOICE_ENGINES_DIR。
4. 官方安装程序会处理 Python、FFmpeg 等依赖；**模型是另一轮明确选择与下载**。不代替用户接受分析统计提示、不启用云端或远程访问。
5. 对 Fork 源码开发，在仓库根目录运行 bun run dev；Electron 将管理本地后端，不要另启重复的服务。包构建：bun run check:electron、bun run dist（依据官方约束）。
6. 本机默认接口为 http://127.0.0.1:3900，按实际配置为准。先 GET /health、GET /openapi.json、GET /v1/audio/voices；查询已安装模型后，得到用户明确同意再下载。
7. Fork 初次构建可能缺失上游签名/发布密钥。**不伪造官方签名，不自动发布安装包，也不将任何凭据写入工作流**。

## 中文与质量规范

- Electron 使用 i18next；中文文件位于 electron/src/renderer/src/i18n/locales/。任何新增 UI 文案遵守项目 AGENTS.md 和 CLAUDE.md 的所有语言词条一致性要求。
- 中文效果取决于实际安装的模型及其语言支持；“646 languages” 不保证普通话声学质量。
- 先用用户自己的声音、演示声音或明确授权的素材。未经同意不克隆他人声音；模型商用权利需要逐个核实。
- 生成前保留原稿；生成后保留模型标识、版本、声线 ID、输入、时间戳、输出文件路径和检查结果，不上传私人语音。
- 不让 Codex 把模型目录、音轨、WAV/MP4、大型二进制文件或 .env/密钥推送到仓库。

## 目录约定（仅用于后续新增工程，不代表已实现）

~~~text
docs/fork-workstation/       # 本 Fork 的中文路线、操作与验收
scripts/fork-workstation/    # 只读诊断和后续安全自动化
# 本机工作目录（不跟踪 Git）
D:\VoiceStudio\projects\<project>\inputs\
D:\VoiceStudio\projects\<project>\outputs\
D:\VoiceStudio\projects\<project>\manifests\
~~~

## 当前需要做什么

打开 [P1 Codex 施工指令](./PHASE1-CODEX.zh-CN.md)，让 Codex 在 **Windows 本机**检查真实硬件、安装 Electron 与模型（须先征询授权）、验证本地服务并生成首个中文测试音频。安装/生成的真实结果必须由机器日志和音频文件证明；GitHub 上的文件不构成已部署证据。

## 同步与风险

- 单独开发分支 + Draft PR；主分支保持和上游尽可能一致。
- 上游同步前先检查冲突；Fork 自有文档/脚本独立放置，减少未来 merge 风险。
- 遵守 AGPL-3.0-only；模型权重另有许可（例如默认 OmniVoice 权重有非商业条款）。发布或商业化前逐项审查。
- 使用本地端口，不主动暴露 0.0.0.0、不做公网端口转发；API 密钥/令牌永不打印入日志。
