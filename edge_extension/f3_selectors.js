// F3 Boss 推荐牛人页 DOM selectors — 集中常量, 未来 DOM 变只改此处
// 2026-04-21 MCP live 探查后校准. 关键发现: 卡片 + 岗位下拉全部在
// <iframe src="/web/frame/recommend/..."> 里, 非 top frame. content.js 需
// 通过 _getRecommendDoc() 取 iframe.contentDocument 再 query.

const F3_SELECTORS = {
  // 页面判定 (top frame URL — 扩展 content.js 的运行上下文)
  PAGE_URL_PATH: '/web/chat/recommend',
  // iframe src path — 用于识别哪个 iframe 是推荐牛人内容区
  RECOMMEND_IFRAME_PATH: '/web/frame/recommend/',

  // ═══ 以下 selector 全部针对 iframe.contentDocument, 非 top frame ═══

  // 顶部岗位选择下拉 (Q8 岗位对齐检查用)
  // 当前选中显示位置: .ui-dropmenu-label (div)
  // 展开列表里当前项: li.job-item.curr span.label
  TOP_JOB_TEXT: '.ui-dropmenu-label',

  // 候选人卡片容器
  CARD_LIST_CONTAINER: 'ul.card-list',
  CARD_ITEM: 'li.card-item',
  // boss_id 在 .card-inner 上, 非 li.card-item
  CARD_INNER: '.card-inner',

  // 单卡片内字段 (都在 li.card-item 内)
  CARD_NAME: 'span.name',
  CARD_BASE_INFO: '.join-text-wrap.base-info',          // "22岁 27年应届生 硕士 刚刚活跃"
  CARD_RECENT_FOCUS: '.expect-wrap .content',           // "北京 全栈工程师"
  CARD_EDUCATION_ROW: '.edu-wrap .content',             // "北京交通大学 软件工程 硕士"
  CARD_WORK_ROW: '.col-3',                              // 顶级容器, 有则含 .timeline-wrap.work-exps
  CARD_WORK_ROW_TIMELINE: '.col-3 .timeline-wrap.work-exps',
  CARD_TAG_ROW: '.row.tags .tags-wrap',
  CARD_TAG_ITEM: '.tag-item',                           // 具体 tag 元素 (skills/院校/排名/推荐理由)
  CARD_TAG_HIGHLIGHT: '.tag-item.highlight',            // 带 highlight 的是推荐理由 ("来自相似职位Python")
  CARD_SALARY: '.salary-wrap span',                     // "3-4K" / "面议" / "5-8K"

  // 打招呼按钮
  CARD_GREET_BTN: 'button.btn.btn-greet',
  // 点完后按钮变化标志 (真机验证后细化; 目前用 disabled + 文本扫描兜底)
  CARD_GREET_BTN_DONE: 'button.btn.btn-greet[disabled], button.btn.btn-greet.disabled',

  // 风控告警元素 (spec §7.3) — 可能出现在 top frame 或 iframe
  RISK_CAPTCHA: '.captcha-wrap',
  RISK_VERIFY: '[class*="verify-dialog"], [class*="captcha-"]',
  RISK_ALERT: '[class*="risk-tip"], [class*="intercept"]',

  // 付费打招呼弹窗 (视为风控)
  PAID_GREET_DIALOG: '[class*="pay-dialog"], [class*="upgrade-dialog"], [class*="exchange-dialog"]',

  // 风控文案模式 (innerText 扫描, 两个 document 都扫)
  RISK_TEXT_PATTERNS: [
    '操作过于频繁',
    '请稍后再试',
    '账号异常',
    '人机验证',
    '开通套餐',
    '升级会员',
    '本次操作失败',
    '已达每日上限',
  ],
};

// 导出给 content.js 用 (Node 单测用; MV3 content script 直接走全局)
if (typeof module !== 'undefined') module.exports = { F3_SELECTORS };
