<template>
  <!-- 登录页：不显示侧边栏 -->
  <router-view v-if="route.path === '/login'" />

  <!-- 主布局 -->
  <el-container v-else class="app-container">
    <el-aside width="220px" class="app-aside">
      <div class="logo">
        <h2>招聘助手</h2>
      </div>
      <el-menu
        :default-active="activeMenu"
        router
        class="app-menu"
      >
        <el-menu-item index="/">
          <el-icon><DataBoard /></el-icon>
          <span>工作台</span>
        </el-menu-item>
        <el-menu-item index="/resumes">
          <el-icon><Document /></el-icon>
          <span>简历库</span>
        </el-menu-item>
        <el-menu-item index="/jobs">
          <el-icon><Briefcase /></el-icon>
          <span>岗位管理</span>
        </el-menu-item>
        <el-menu-item index="/hitl">
          <el-icon><View /></el-icon>
          审核队列
          <el-badge v-if="hitlPendingCount > 0" :value="hitlPendingCount" class="hitl-badge" />
        </el-menu-item>

        <el-menu-item index="/skills">
          <el-icon><Collection /></el-icon>
          技能库
        </el-menu-item>
        <el-menu-item index="/interviewers">
          <el-icon><User /></el-icon>
          <span>面试官管理</span>
        </el-menu-item>
        <el-menu-item index="/interviews">
          <el-icon><Calendar /></el-icon>
          <span>面试安排</span>
        </el-menu-item>
        <el-menu-item index="/notifications">
          <el-icon><Bell /></el-icon>
          <span>通知记录</span>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>
          <span>设置</span>
        </el-menu-item>
      </el-menu>
      <div class="user-bar" @click="logout">
        <span class="user-name">{{ displayName }}</span>
        <span class="logout-text">退出</span>
      </div>
    </el-aside>
    <el-main class="app-main">
      <div v-if="!networkOk" style="background: #f56c6c; color: white; text-align: center; padding: 8px; font-size: 14px;">
        ⚠ 与服务器断开连接，请检查服务是否正在运行
      </div>
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { hitlApi } from './api'
import { View, Collection } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const activeMenu = computed(() => route.path)

const displayName = computed(() => {
  try {
    const user = JSON.parse(localStorage.getItem('user') || '{}')
    return user.display_name || user.username || ''
  } catch { return '' }
})

function logout() {
  localStorage.removeItem('token')
  localStorage.removeItem('user')
  router.push('/login')
}

const networkOk = ref(true)
let healthTimer = null

const hitlPendingCount = ref(0)
let pollTimer = null

async function refreshPending() {
  try {
    const resp = await hitlApi.list({ status: 'pending', limit: 1 })
    hitlPendingCount.value = resp.total || 0
  } catch (e) {
    console.error('refresh pending failed', e)
  }
}

const checkHealth = async () => {
  try {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 5000)
    const res = await fetch('/api/health', { signal: controller.signal })
    clearTimeout(timeout)
    networkOk.value = res.ok
  } catch {
    networkOk.value = false
  }
}

const beforeUnloadHandler = (e) => {
  const hasDialog = document.querySelector('.el-dialog:not([style*="display: none"])') ||
                    document.querySelector('.el-message-box:not([style*="display: none"])')
  if (hasDialog) {
    e.preventDefault()
    e.returnValue = ''
  }
}

onMounted(() => {
  checkHealth()
  healthTimer = setInterval(checkHealth, 30000)
  window.addEventListener('beforeunload', beforeUnloadHandler)
  refreshPending()
  pollTimer = setInterval(refreshPending, 5 * 60 * 1000)
})

onUnmounted(() => {
  clearInterval(healthTimer)
  window.removeEventListener('beforeunload', beforeUnloadHandler)
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body, #app { height: 100%; }

.app-container { height: 100vh; }
.app-aside {
  background: #001529;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.logo {
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-bottom: 1px solid rgba(255,255,255,0.1);
  flex-shrink: 0;
}
.logo h2 { color: #fff; font-size: 18px; font-weight: 600; }
.app-menu {
  border-right: none;
  background: #001529;
  flex: 1;
}
.app-menu .el-menu-item {
  color: rgba(255,255,255,0.65);
}
.app-menu .el-menu-item:hover,
.app-menu .el-menu-item.is-active {
  color: #fff;
  background: #1677ff;
}
.user-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-top: 1px solid rgba(255,255,255,0.1);
  cursor: pointer;
  flex-shrink: 0;
}
.user-bar:hover { background: rgba(255,255,255,0.05); }
.user-name {
  color: rgba(255,255,255,0.65);
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.logout-text {
  color: rgba(255,255,255,0.4);
  font-size: 12px;
  flex-shrink: 0;
}
.hitl-badge {
  margin-left: 8px;
}
.app-main {
  background: #f0f2f5;
  padding: 24px;
  overflow-y: auto;
}
</style>
