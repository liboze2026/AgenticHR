// F3 Boss 推荐牛人页 DOM selectors — 集中常量, 未来 DOM 变只改此处
// 2026-04-21 MCP 登入实地探查的基础版本; T6 实现时会在真实页面 devtools 里精确化

const F3_SELECTORS = {
  // 页面判定
  PAGE_URL_PATH: '/web/chat/recommend',

  // 顶部岗位选择下拉（Q8 岗位对齐检查用）
  TOP_JOB_DROPDOWN: '.job-select-dropdown, [class*="job-select"], [class*="job-name"]',
  TOP_JOB_TEXT: '.job-select-dropdown .selected-text, [class*="job-select"] span',

  // 候选人卡片容器 — 列表项
  CARD_LIST_CONTAINER: '.geek-recommend-list, .recommend-list, [class*="candidate-list"]',
  CARD_ITEM: '.geek-item, .candidate-item, [class*="recommend-card"]',

  // 单卡片内
  CARD_NAME: '.geek-name, [class*="name"]:not([class*="school-name"])',
  CARD_BASE_INFO: '.geek-base-info, [class*="base-info"]',  // 含年龄/毕业年/学历/活跃状态
  CARD_RECENT_FOCUS: '.geek-expect, [class*="expect"]',     // 最近关注行
  CARD_EDUCATION_ROW: '.geek-edu, [class*="edu-row"]',      // 学历·学校·专业·学位
  CARD_WORK_ROW: '.geek-work, [class*="work-row"]',         // 工作经历简述
  CARD_TAG_ROW: '.geek-tags, [class*="tag-list"]',          // tag 集合
  CARD_TAG_ITEM: '.tag-item, [class*="tag"]',
  CARD_SALARY: '.salary-tag, [class*="salary"]',
  CARD_ACTIVE_STATUS: '.active-status, [class*="active-time"]',

  // 打招呼按钮（list-level, 非 modal）
  CARD_GREET_BTN: '.btn-greet, [class*="greet-btn"], button:contains("打招呼")',
  // 点完后按钮变化标志（T1 实测填准）
  CARD_GREET_BTN_DONE: '.btn-greet.done, [class*="greet-done"]',

  // 风控告警元素 (spec §7.3)
  RISK_CAPTCHA: '.captcha-wrap',
  RISK_VERIFY: '[class*="verify"]',
  RISK_ALERT: '[class*="risk-tip"], [class*="intercept"]',

  // 付费打招呼弹窗（视为风控）
  PAID_GREET_DIALOG: '[class*="pay-dialog"], [class*="upgrade-dialog"]',

  // 风控文案模式（innerText 扫描）
  RISK_TEXT_PATTERNS: [
    '操作过于频繁',
    '请稍后再试',
    '账号异常',
    '人机验证',
    '开通套餐',
    '升级会员',
  ],
};

// 导出给 content.js 用
if (typeof module !== 'undefined') module.exports = { F3_SELECTORS };
