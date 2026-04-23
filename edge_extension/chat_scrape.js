// Pure DOM parser for Boss 直聘 chat page (zhipin.com/web/chat/index).
// Real selectors verified on live page 2026-04-23 against 李博泽 conversation.
// Structure:
//   Left panel:  .geek-item.selected [data-id=<boss_id>]  (currently selected candidate)
//   Right panel (root arg): .chat-conversation  +  .name-box  +  .chat-message-list
//   Each message: .message-item
//     child:  .item-friend   (sent by candidate)   → sender_id = boss_id
//             .item-myself   (sent by HR)          → sender_id = "self"
//             .item-system   (system notice)       → skipped
//     text:   .text
// Exported as window globals (not ES module) so content.js can consume without import.

const CHAT_SELECTORS = {
  root: ".chat-conversation",
  selectedItem: ".geek-item.selected",
  selectedDataIdField: "data-id",
  nameBox: ".name-box",
  jobIntentionSel: ".position-content .position-name, .geek-item.selected .source-job",
  messageItem: ".chat-message-list .message-item",
  friendMarker: ".item-friend",
  myselfMarker: ".item-myself",
  systemMarker: ".item-system",
  textNode: ".text",
};

function parseChatFromDOM(root, sel) {
  sel = sel || CHAT_SELECTORS;
  if (!root) return null;
  const selected = document.querySelector(sel.selectedItem);
  const boss_id = selected ? (selected.getAttribute(sel.selectedDataIdField) || "") : "";
  const name = (document.querySelector(sel.nameBox)?.textContent || "").trim();
  const job_intention = (document.querySelector(sel.jobIntentionSel)?.textContent || "").trim();
  const messages = [];
  document.querySelectorAll(sel.messageItem).forEach((item) => {
    if (item.querySelector(sel.systemMarker)) return;
    const isFriend = !!item.querySelector(sel.friendMarker);
    const isSelf = !!item.querySelector(sel.myselfMarker);
    if (!isFriend && !isSelf) return;
    const textEl = item.querySelector(sel.textNode);
    const content = (textEl?.textContent || "").trim();
    if (!content) return;
    messages.push({
      sender_id: isFriend ? boss_id : "self",
      content,
    });
  });
  return { boss_id, name, job_intention, messages };
}

window.CHAT_SELECTORS = CHAT_SELECTORS;
window.parseChatFromDOM = parseChatFromDOM;
