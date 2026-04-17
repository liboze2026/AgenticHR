<template>
  <div class="login-container">
    <div class="login-card">
      <h1 class="login-title">招聘助手</h1>
      <p class="login-subtitle">{{ isRegister ? '创建账号' : '登录' }}</p>

      <div class="login-form">
        <div class="form-item">
          <label>用户名</label>
          <el-input v-model="form.username" placeholder="请输入用户名" @keyup.enter="submit" />
        </div>
        <div class="form-item">
          <label>密码</label>
          <el-input v-model="form.password" type="password" placeholder="请输入密码（至少6位）" show-password @keyup.enter="submit" />
        </div>
        <div v-if="isRegister" class="form-item">
          <label>确认密码</label>
          <el-input v-model="confirmPassword" type="password" placeholder="请再次输入密码" show-password @keyup.enter="submit" />
        </div>
        <div v-if="isRegister" class="form-item">
          <label>显示名称</label>
          <el-input v-model="form.display_name" placeholder="可选，如：李HR" @keyup.enter="submit" />
        </div>

        <el-button type="primary" class="login-btn" :loading="loading" @click="submit">
          {{ isRegister ? '注册并进入' : '登录' }}
        </el-button>

        <p v-if="!isRegister" class="switch-hint">
          还没有账号？<span class="switch-link" @click="isRegister = true">注册新账号</span>
        </p>
        <p v-if="isRegister" class="switch-hint">
          已有账号？<span class="switch-link" @click="isRegister = false">返回登录</span>
        </p>

        <p v-if="errorMsg" class="error-msg">{{ errorMsg }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

const router = useRouter()
const isRegister = ref(false)
const loading = ref(false)
const errorMsg = ref('')
const form = ref({ username: '', password: '', display_name: '' })
const confirmPassword = ref('')

onMounted(async () => {
  try {
    const resp = await fetch('/api/auth/status')
    const data = await resp.json()
    isRegister.value = !data.has_user
  } catch {
    // server not reachable, show login anyway
  }
})

async function submit() {
  errorMsg.value = ''
  if (!form.value.username.trim()) { errorMsg.value = '请输入用户名'; return }
  if (form.value.password.length < 6) { errorMsg.value = '密码至少6位'; return }
  if (isRegister.value && form.value.password !== confirmPassword.value) { errorMsg.value = '两次密码输入不一致'; return }

  loading.value = true
  const endpoint = isRegister.value ? '/api/auth/register' : '/api/auth/login'
  try {
    const resp = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value),
    })
    const data = await resp.json()
    if (!resp.ok) {
      errorMsg.value = data.detail || '操作失败'
      return
    }
    localStorage.setItem('token', data.token)
    localStorage.setItem('user', JSON.stringify(data.user))
    ElMessage.success(isRegister.value ? '注册成功' : '登录成功')
    router.replace('/')
  } catch {
    errorMsg.value = '无法连接服务器'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-container {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}
.login-card {
  background: white;
  border-radius: 12px;
  padding: 48px 40px;
  width: 400px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.15);
}
.login-title {
  text-align: center;
  font-size: 28px;
  color: #1a1a2e;
  margin-bottom: 4px;
}
.login-subtitle {
  text-align: center;
  color: #909399;
  margin-bottom: 32px;
  font-size: 15px;
}
.form-item {
  margin-bottom: 20px;
}
.form-item label {
  display: block;
  font-size: 13px;
  color: #606266;
  margin-bottom: 6px;
  font-weight: 500;
}
.login-btn {
  width: 100%;
  height: 42px;
  font-size: 15px;
  margin-top: 8px;
}
.error-msg {
  color: #f56c6c;
  font-size: 13px;
  text-align: center;
  margin-top: 16px;
}
.switch-hint { text-align: center; font-size: 13px; color: #909399; margin-top: 16px; }
.switch-link { color: #409eff; cursor: pointer; }
.switch-link:hover { text-decoration: underline; }
</style>
