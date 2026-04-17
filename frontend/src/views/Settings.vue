<template>
  <div>
    <h2 style="margin-bottom: 24px">设置</h2>
    <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 20px;">
      <template #title>配置修改说明</template>
      <template #default>
        配置文件位于程序目录下的 <b>.env</b> 文件中。修改后需要<b>重启服务</b>才能生效。
      </template>
    </el-alert>
    <el-tabs>
      <el-tab-pane label="AI 配置">
        <el-card>
          <el-form label-width="120px">
            <el-form-item label="AI 状态">
              <el-tag :type="aiStatus.enabled ? 'success' : 'info'">{{ aiStatus.enabled ? '已启用' : '未启用' }}</el-tag>
              <el-tag :type="aiStatus.configured ? 'success' : 'warning'" style="margin-left: 8px">{{ aiStatus.configured ? '已配置' : '未配置' }}</el-tag>
            </el-form-item>
            <el-form-item label="模型">{{ aiStatus.model || '-' }}</el-form-item>
            <el-form-item>
              <p style="color: #999; font-size: 13px">在 .env 文件中设置 AI_ENABLED=true 并填入 API Key</p>
            </el-form-item>
            <el-form-item>
              <el-button @click="testService('ai')">检测状态</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>
      <el-tab-pane label="Boss 直聘">
        <el-card>
          <el-form label-width="120px">
            <el-form-item label="适配器状态">
              <el-tag :type="bossStatus.is_available ? 'success' : 'info'">{{ bossStatus.adapter_type }}</el-tag>
            </el-form-item>
            <el-form-item label="今日操作次数">{{ bossStatus.operations_today }} / {{ bossStatus.max_operations_today }}</el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>
      <el-tab-pane label="飞书">
        <el-card>
          <el-form label-width="120px">
            <el-form-item label="连接状态">
              <el-tag :type="feishuStatus.configured ? 'success' : 'warning'">{{ feishuStatus.configured ? '已配置' : '未配置' }}</el-tag>
            </el-form-item>
            <el-form-item>
              <p style="color: #999; font-size: 13px">飞书、邮箱、腾讯会议的凭证请在 .env 文件中配置</p>
            </el-form-item>
            <el-form-item>
              <el-button @click="testService('feishu')">检测状态</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api, { aiApi, bossApi } from '../api'

const aiStatus = ref({ enabled: false, configured: false, model: '' })
const bossStatus = ref({ adapter_type: '', is_available: false, operations_today: 0, max_operations_today: 0 })
const feishuStatus = ref({ configured: false })

async function loadStatus() {
  try { aiStatus.value = await aiApi.status() } catch (e) { console.error('aiApi.status failed:', e) }
  try { bossStatus.value = await bossApi.status() } catch (e) { console.error('bossApi.status failed:', e) }
  try { feishuStatus.value = await api.get('/feishu/status') } catch (e) { console.error('feishu/status failed:', e) }
}

onMounted(loadStatus)

const serviceLabels = {
  feishu: '飞书',
  ai: 'AI',
  email: '邮箱',
  meeting: '腾讯会议',
}

const testService = async (serviceName) => {
  try {
    const res = await fetch('/api/health')
    const data = await res.json()
    const svc = data.services?.[serviceName]
    if (svc?.configured) {
      ElMessage.success(serviceLabels[serviceName] + ' 已配置')
    } else {
      ElMessage.warning(serviceLabels[serviceName] + ' 未配置，请在 .env 中设置')
    }
  } catch {
    ElMessage.error('无法连接服务器')
  }
}
</script>
