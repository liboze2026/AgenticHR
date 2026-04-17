// background.js — 招聘助手 Service Worker

chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    chrome.storage.local.set({
      serverUrl: "http://127.0.0.1:8000",
    });
    console.log("招聘助手已安装，默认服务器地址: http://127.0.0.1:8000");
  }
});
