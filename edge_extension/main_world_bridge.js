// main_world_bridge.js — runs in MAIN world so it can access page-side
// Vue component internals (e.g. el.__vue__) which are invisible from the
// extension's isolated content-script world.
// Responds to postMessage requests from content.js.

(function () {
  window.addEventListener("message", (e) => {
    if (e.source !== window || !e.data?.__intakeBridge) return;
    const { cmd, id, bossId } = e.data;
    const ulVue = document.querySelector(".user-list")?.__vue__;

    if (cmd === "get_datasources") {
      // Scroll virtual list to bottom repeatedly to trigger lazy-load of all pages
      async function loadAll() {
        if (!ulVue) return null;
        let prev = -1;
        for (let i = 0; i < 30; i++) {  // max 30 scroll attempts (safety cap)
          const ds = ulVue.$props?.dataSources || [];
          if (ds.length === prev) break;  // no new items loaded
          prev = ds.length;
          ulVue.scrollToIndex(ds.length - 1);
          await new Promise(r => setTimeout(r, 700));
        }
        return ulVue.$props?.dataSources || null;
      }
      loadAll().then(ds => {
        const data = ds
          ? ds.map((d) => ({
              uniqueId: d.uniqueId,
              name: d.name || "",
              jobName: d.jobName || "",
            }))
          : null;
        window.postMessage({ __intakeBridgeReply: true, id, data }, "*");
      });
      return;  // reply sent async inside loadAll().then()
    } else if (cmd === "scroll_to_geek") {
      const ds = ulVue?.$props?.dataSources || [];
      const idx = ds.findIndex((d) => String(d.uniqueId) === String(bossId));
      if (idx !== -1 && ulVue?.scrollToIndex) ulVue.scrollToIndex(idx);
      window.postMessage({ __intakeBridgeReply: true, id, idx }, "*");
    } else if (cmd === "send_text") {
      const editor = document.querySelector(".conversation-editor");
      const vm = editor?.__vue__;
      let ok = false;
      if (vm && typeof vm.sendText === "function") {
        try { vm.sendText(); ok = true; } catch (_) {}
      }
      window.postMessage({ __intakeBridgeReply: true, id, ok }, "*");
    }
  });
})();
