# P1｜交给 Codex 的 Windows 本地部署与首段中文配音施工指令

**目标**：在你的 Windows PC 上以不破坏已有设置的方式安装/启动 VoiceStudio Electron，确认本机 API，并在经许可的模型、授权声线条件下生成一段真正可播放的中文 WAV。

以下是可直接提供给在 Windows 本机运行的 Codex 的任务说明。

## 执行上下文

- GitHub 仓库：lv5accelerator-xy/VoiceStudio
- 工作分支：codex/p0-local-music-workstation（如需要变更代码，另开功能分支与 Draft PR）
- 官方上游：debpalash/VoiceStudio
- 优先官方稳定安装版验证使用体验；需要开发/改动时再从 Fork 源码运行。
- 维护中桌面端：Electron；不要部署归档的 Tauri。

## Codex 施工任务

1. 先读取本仓库 AGENTS.md、CLAUDE.md、docs/install/agent.md、docs/install/windows.md、electron/README.md、skills/voicestudio/SKILL.md，不要用旧版本网上教程替代实际仓库说明。
2. 查看 Windows 版本和架构、CPU、GPU 型号/驱动、物理内存、系统盘/数据盘剩余容量，检查是否已有 VoiceStudio、Bun、Node、Python、FFmpeg，以及已有本地模型/配置。可运行 scripts/fork-workstation/check-windows.ps1。不得打印环境中的密钥或个人素材。
3. 如已安装，优先复用。缺失时先说明推荐的官方 Release 名称、版本、签名/SHA256 核对、预计磁盘需求；执行安装时遵守本机操作权限。若选择源码开发，使用 bun run dev 从仓库根目录启动，避免重复启动 FastAPI。
4. 用户未同意前不得下载模型，也不得替用户勾选分析统计、开启云服务、外网访问或远程后端。列出候选中文 TTS 引擎及其模型大小、许可证、硬件适用性和预期质量，等待明确授权后再进行该项下载。无需为了测试就复制陌生人的声音。
5. 启动应用、检查默认 /health 和 /openapi.json，按运行时 API 协议获取真实 voice ID 与已安装模型，而不是猜测 ID。仅使用本人语音或演示/已授权声线。
6. 调用已发现的 API 生成短中文台词，例如：『你好，这里是我的本地 AI 配音工作站。』，输出 WAV 到本地工作目录，检查 HTTP 返回、文件头、时长、是否能实际播放。若失败，报告错误原因，不冒充成功。
7. 输出一份 P1 验收记录：真实版本、OS、CPU/GPU 加速方式、模型名称与许可证、是否下载、数据目录、API 地址、WAV 完整路径/格式/时长、问题、下一步。敏感路径和凭据不得进 GitHub。
8. 仅在用户明确要求时才把无隐私的代码/文档更改提交到新分支 + Draft PR。不得自动合并、打包签名发布或使用上游私有凭据。

## 验收清单

- [ ] Electron 正常打开；无重复 FastAPI 后端
- [ ] GET /health 返回成功
- [ ] GET /openapi.json 可用；接口由运行中后端发现
- [ ] CPU/GPU 加速方式由真实设备确认
- [ ] 确认所用模型和权重许可，用户已授权模型下载（如果发生）
- [ ] 至少一段真实中文 WAV 可以播放
- [ ] 无未经授权的声音克隆、云上传或凭据泄露
- [ ] 提供真实运行日志摘要而非仅 GitHub CI 通过

## 参考命令（由 Codex 先检查实际环境再执行）

~~~powershell
# PowerShell，在 Fork 根目录：
powershell -ExecutionPolicy Bypass -File .\scripts\fork-workstation\check-windows.ps1

# 仅当需要源码开发、且本机准备好环境：
bun run dev

# 有代码变更时的 Electron 质量检查：
bun run check:electron
~~~

> 说明：GitHub Actions 的构建成功不等于已在你的 Windows 电脑完成安装。无签名测试包也不等于官方稳定安装包。验收必须以本机实际打开软件、访问 API 和音频播放为准。
