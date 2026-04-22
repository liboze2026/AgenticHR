# F5 — 单人手动采集 手工 QA 步骤

## 前置
1. 后端：`alembic upgrade head` → 迁移 0012 应用；`F4_ENABLED=false`（默认）
2. 前端：`pnpm dev` 启动
3. 登录一个 HR 账号
4. Edge 加载 `edge_extension/` 目录（开发者模式）
5. HR 自己的浏览器登录 Boss 直聘小号

## 步骤 1 — 插件手动采集（popup 按钮）
1. 在 Boss 直聘中打开一个真实候选人的聊天框（URL 形如 `https://www.zhipin.com/web/chat/index?id=xxx`）
2. 点插件 popup → "采集当前聊天候选人"
3. **预期**：页面右上角出现 `【采集】...` 浮层；后端 `/api/intake/candidates` 出现该候选人，状态 `collecting` 或 `awaiting_reply`
4. **真实页面选择器调校**：如果浮层报"抓取聊天信息失败 (boss_id 未识别)"，打开 DevTools Elements 面板，找到真实的聊天容器 DOM，更新 `edge_extension/chat_scrape.js` 中的 `CHAT_SELECTORS`

## 步骤 2 — /intake "开始沟通" 接管
1. 浏览器打开 `http://localhost:3000/intake`
2. 应看到上一步添加的候选人
3. 点该行 "开始沟通"
4. **预期**：新标签页打开 Boss 聊天 deep link（URL 含 `intake_candidate_id=X`）；页面载入后右上角浮层显示 `【采集】下一步: send_hard`；聊天输入框自动填入问题（硬性 3 问）并发送；浮层更新为 `问题已发送`

## 步骤 3 — 候选人回复后再触发
1. HR 替身账号回复 "明天到岗，能实习 6 个月，周三下午面试可以"
2. HR 回到 `/intake`，点该行 "开始沟通" 再次触发
3. **预期**：slot 填充 arrival_date / intern_duration / free_slots；由于 PDF 还没到，浮层显示 `下一步: request_pdf`；插件自动点"求简历"按钮

## 步骤 4 — PDF 到手后
1. 候选人发简历 PDF（或手动上传测试 PDF）
2. 再次触发采集
3. **预期**：`pdf_present=true` 被后端识别，决策走 `complete`（如果岗位无 `competency_model`）或 `send_soft` → 发软性问题
4. 如果走到 `complete`：数据库 `intake_candidates.intake_status='complete'`，`resumes` 表新建一行（由 `promote_to_resume` 搬家）；`/resumes` 页面应看到新行

## 步骤 5 — 简历库过滤验证
1. 打开 `/resumes`
2. **预期**：顶部横幅 "简历库语义 — 本列表仅显示已完成信息采集..."
3. 只显示 `intake_status='complete'` 的行；F3 打过招呼但未采集完成的候选人不出现

## 选择器待调校清单（T14/T15 placeholders）
- [ ] `edge_extension/chat_scrape.js` `CHAT_SELECTORS.*` — 聊天容器/消息列表/boss_id 属性
- [ ] `edge_extension/content.js` `f5_typeAndSendChatMessage` — `.chat-input textarea` 和发送按钮
- [ ] `edge_extension/content.js` `f5_clickRequestResumeButton` — `/求简历|索要简历/` 按钮文案
- [ ] `edge_extension/content.js` `f5_checkPdfReceived` — `.attachment-card` + `data-sender` 属性
- 调校后回填 `chat_scrape.js` / `content.js`，重新加载插件

## 常见问题排查
- 浮层不出现：检查 `manifest.json` matches 是否覆盖当前 URL；Extensions 页看 content script 是否注入
- 401 Unauthorized：`chrome.storage.local.authToken` 未设置，通过 popup 登录
- CORS 错：后端 CORS 白名单加上 zhipin.com
