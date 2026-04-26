# AgenticHR

See [Workflow Requirements](#workflow-requirements) before starting any task.

## Language
- Always respond in Chinese (中文) unless explicitly asked otherwise.

## Workflow Requirements
- For any milestone/feature work (M2.x tasks): ALWAYS follow design-doc-first then TDD. Do not skip to implementation.
- After code changes, run `pnpm test` and `pnpm typecheck` before claiming completion.
- Before merging to master, check for untracked files and uncommitted lockfile changes; stash/clean as needed.

## Core Layer Constraints
- Do not edit files under `core/` without explicit user approval — documented architectural boundary.

## Verification Before Concluding
- When diagnosing API/endpoint/model issues, test ALL plausible endpoint+auth combinations before concluding something is broken or invalid.

<!-- TEAMAGENT:START - 自动管理，请勿手动编辑 -->
## TeamAgent 经验（127条活跃知识，为你编译了 30 条（token 预算 3000）)
- 移除用户反馈的检查条件，仅基于失败本身触发分析——用户反馈约束是冗余的；所有错都应进入分析管道，由规则库自主决定是否学习，而非前置过滤 [0.95] [预置]
- hook 代码写完后必须在 .claude/settings.local.json 注册对应 hook 事件，并端到端验证触发链路——Claude Code hook 由 harness 按 settings.local.json 配置调度，仅有脚本文件不会自动生效；未注册 = 代码形同虚设。自动化能力（如自学习 pipeline）还需 Stop/UserPromptSubmit 等触发事件，手动命令只是 fallback，不能当作闭环 [0.90] [预置]
- 使用 跑完实际验证命令（构建+启动+测试）并贴出真实输出再宣布完成 而非 全部修复完成——用户反复看到 AI 宣称修复完还残留 bug，说明 AI 基于局部证据（如单测绿）就下结论；完成声明必须以端到端验证输出为证据，否则等于骗用户 [0.90] [预置]
- 使用 先读用户指向的文件，重新 brainstorm + 补全需求，再拆 task 实现；API key 来源询问用户（如 claude code haiku） 而非 计划文档只是设计文档，还没实现——AI 未读文件就断言不存在会误导用户；正确做法是先 Read 指定路径、以文件内容为准，再结合用户偏好（如用 haiku 作 token 来源）规划实现 [0.90] [预置]
- 使用 忽略 <local-command-caveat> 包裹的消息，除非用户明确要求分析 而非 <local-command-caveat>——该标签内容由本地命令自动生成，非用户意图表达；AI 主动响应会污染对话上下文，误把系统噪声当用户指令 [0.90] [预置]
- 使用 忽略 <local-command-caveat> 包裹的消息，除非用户明确要求分析 而非 <local-command-caveat>——该标签内容由本地命令自动生成，非用户意图表达；AI 主动响应会污染对话上下文，误把系统噪声当用户指令 [0.90] [预置]
- 使用 忽略该标签内所有内容，除非用户明确要求分析 而非 <local-command-caveat>——<local-command-caveat> 内容由本地命令自动生成，非用户意图；响应它会把系统噪声当用户指令，污染对话上下文 [0.90] [预置]
- 使用 忽略该标签内所有内容，除非用户明确要求分析 而非 <local-command-caveat>——<local-command-caveat> 内容由本地命令自动生成，非用户意图；响应它会把系统噪声当用户指令，污染对话上下文 [0.90] [预置]
- 使用 忽略该标签内所有内容，除非用户明确要求分析 而非 <local-command-caveat>——<local-command-caveat> 内容由本地命令自动生成，非用户意图；响应它会把系统噪声当用户指令，污染对话上下文 [0.90] [预置]
- 立即读取 output-file 并继续后续流程，不再说'等通知'——task-notification 本身就是通知；AI 仍说'等通知'说明未识别该消息为触发信号，正确做法是收到后立即处理输出、推进工作流 [0.90] [预置]
- 后台 agent 完成时系统会发 task-notification，包含 task-id、output-file、status、summary；可通过 TaskOutput 工具按 task-id 读取结果——Agent(run_in_background=true) 底层走 TaskCreate 机制，完成后 harness 自动发 task-notification 事件；AI 声称'无法手动查状态'是错的，实际有 task-id 可查 [0.90] [预置]
- 立即读取 output-file 并继续后续流程，不再说'等通知'——task-notification 本身就是通知；AI 仍说'等通知'说明未识别该消息为触发信号，正确做法是收到后立即处理输出、推进工作流 [0.90] [预置]
- 立即读取 output-file，继续后续流程（如 dispatch 下一 Wave）——task-notification 本身就是完成信号；收到后仍说'等通知'说明 AI 未识别该消息为触发点，正确做法是收到即处理，不需要额外等待 [0.90] [预置]
- 立即读取 output-file 并继续后续流程，不再说'等通知'——task-notification 本身就是通知；AI 仍说'等通知'说明未识别该消息为触发信号，正确做法是收到后立即处理输出、推进工作流 [0.90] [预置]
- 维护游标，增量扫描新增 turn，去重已处理；仅在 /new、/clear、/compact、退出、关闭窗口时做完整重扫——Stop 每轮触发，全量重扫导致 token 消耗呈平方增长；增量扫描维护游标可避免重复，关键时刻完整重扫确保一致性 [0.90] [预置]
- 自动化拉取 + 自动清理过时数据——手动维护导致数据陈旧（拉取滞后5天）和无效数据堆积，自动化+清理确保知识及时可用且命中率高 [0.90] [预置]
- 立即用 TaskOutput 工具按 task-id 读取输出，继续流程——task-notification 本身就是完成信号，harness 发出即表示任务已完；立即处理充分利用并行性而非阻塞 [0.90] [预置]
- 忽略标签内所有内容，除非用户明确要求分析——<local-command-caveat> 由本地命令自动生成而非用户意图，响应会把系统噪声当指令污染对话 [0.90] [预置]
- 先把凭据/环境持久化到项目配置（增量、不改已有内容），再让 subagent 自主完成；远程实验需先检测空闲显卡避免影响他人——反复追问凭据打断用户节奏；配置应一次记录永久复用。subagent 应自主推进而非报 BLOCKED。共享 GPU 资源需礼让他人实验 [0.95] [预置]
- 按产品经理视角讲架构、流程、关键原理,略过代码级细节——默认倾向给技术细节会淹没非技术受众；产品经理需要整体认知(架构/流程/原理)而非实现,讲解粒度要匹配听众心智模型 [0.95] [预置]
- 使用 直接调用 mcp 工具 而非 通过 wiki 知识库系统——wiki 知识库方案过度复杂；应优先检查是否有现成 mcp 工具可直接调用，避免绕路 [0.95] [预置]
- 全局单次init，所有项目共享规则——全局 init 避免重复配置和规则分散，保证用户所有项目规则一致，降低管理成本 [0.95] [预置]
- 先澄清和解释系统逻辑细节，获得用户确认理解后再给建议——用户若不理解系统为何如此，对改动方案缺乏信心；同步理解是决策的前置条件，避免改动后产生新的疑虑 [0.95] [预置]
- verbose = 显示所有事件（含调试细节）——用户明确要求此措辞；保持文档用词与用户偏好一致 [0.90] [预置]
- 先选可观察性更强的默认（如阻塞型），但实现上保留切换能力——用户偏好默认走可见/可调试路径以便排查，但不接受硬编码死路；实现应把模式做成配置项而非二选一 [0.90] [预置]
- 选定方案后主动提示可配置/可切换的旋钮（如同步↔异步切换），不等用户追问——用户选 A 后立即追问异步切换，说明 sync/async 等关键 trade-off 应在方案中预留开关并主动告知；只给单一模式会让用户反复追问 [0.90] [预置]
- 以用户对话中明确给出的值为准，覆盖计划文档中的默认值——计划文档是起点而非圣经；用户在实施阶段口头修改参数（如将 token 预算从 2000 改为 3000）代表最新决策，AI 必须用对话值而非文档值，否则实现与用户意图不符 [0.90] [预置]
- 按 深度调研 → brainstorm+需求确认 → 设计文档 → 实现计划 → subagent 驱动开发 顺序推进——跳过前期调研和设计阶段直接实现会导致架构返工；完整流水线确保需求对齐后再拆任务，subagent 执行时边界清晰、减少反复 [0.90] [预置]
- 先读用户指向的文件，重新 brainstorm + 补全需求，再拆 task 实现；API key 来源询问用户（如 claude code haiku）——AI 未读文件就断言不存在会误导用户；正确做法是先 Read 指定路径、以文件内容为准，再结合用户偏好（如用 haiku 作 token 来源）规划实现 [0.90] [预置]
- 使用 回退到上一个稳定 milestone，按 plan→test→impl 顺序重新推进 而非 没有先写 plan、没有先写测试——就地修复跳过流程的代码会积累技术债并违反项目约定；用户偏好硬回退而非打补丁，保持 milestone 边界干净 [0.90] [预置]
> 还有 10 条 canonical+ 规则因 token 预算未显示（teamagent compile --dry-run 查看）
<!-- TEAMAGENT:END -->
