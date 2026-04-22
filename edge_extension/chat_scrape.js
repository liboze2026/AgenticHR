// Pure DOM parser — selectors are PLACEHOLDERS. Verify via DevTools on live page (see TODO at bottom).
// Exported as window globals (not ES module) so content.js can consume without import.

const CHAT_SELECTORS = {
  root: ".chat-conversation",
  bossIdAttr: "[data-boss-id]",
  bossIdField: "data-boss-id",
  name: ".user-info .name",
  jobIntention: ".user-info .position",
  messageList: ".message-list .msg-row",
  messageSenderAttr: "data-sender",
  messageContent: ".msg-bubble",
};

function parseChatFromDOM(root, sel) {
  sel = sel || CHAT_SELECTORS;
  if (!root) return null;
  const idEl = root.querySelector(sel.bossIdAttr);
  const boss_id = idEl ? idEl.getAttribute(sel.bossIdField) : "";
  const name = (root.querySelector(sel.name)?.textContent || "").trim();
  const job_intention = (root.querySelector(sel.jobIntention)?.textContent || "").trim();
  const messages = [];
  root.querySelectorAll(sel.messageList).forEach((row) => {
    const sender_id = row.getAttribute(sel.messageSenderAttr);
    const content = (row.querySelector(sel.messageContent)?.textContent || "").trim();
    if (content) messages.push({ sender_id, content });
  });
  return { boss_id, name, job_intention, messages };
}

// Expose globals for content.js
window.CHAT_SELECTORS = CHAT_SELECTORS;
window.parseChatFromDOM = parseChatFromDOM;

// TODO: verify CHAT_SELECTORS against live boss.zhipin.com/web/chat/index via DevTools Elements panel.
// These are placeholders and WILL need tuning.
