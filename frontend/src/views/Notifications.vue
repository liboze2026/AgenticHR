<template>
  <div>
    <div style="display: flex; justify-content: space-between; margin-bottom: 16px">
      <h2>通知记录</h2>
      <el-button type="danger" plain @click="clearAll">清空全部</el-button>
    </div>
    <el-table :data="pagedItems" stripe v-loading="loading">
      <el-table-column prop="recipient_name" label="接收人" width="120" />
      <el-table-column prop="recipient_type" label="类型" width="90">
        <template #default="{ row }">{{ row.recipient_type === 'candidate' ? '候选人' : '面试官' }}</template>
      </el-table-column>
      <el-table-column prop="channel" label="渠道" width="90">
        <template #default="{ row }">{{ {email:'邮件',feishu:'飞书消息',feishu_pdf:'飞书简历',calendar:'飞书日程',template:'消息模板'}[row.channel] || row.channel }}</template>
      </el-table-column>
      <el-table-column prop="subject" label="主题" show-overflow-tooltip />
      <el-table-column prop="status" label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.status === 'sent' ? 'success' : row.status === 'failed' ? 'danger' : 'info'" size="small">
            {{ row.status === 'sent' ? '已发送' : row.status === 'failed' ? '失败' : '已生成' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="时间" width="180">
        <template #default="{ row }">{{ new Date(row.created_at).toLocaleString('zh-CN') }}</template>
      </el-table-column>
      <el-table-column label="操作" width="80">
        <template #default="{ row }">
          <el-button size="small" @click="viewContent(row)">查看</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-if="logs.length > pageSize"
      v-model:current-page="currentPage"
      :page-size="pageSize"
      :total="logs.length"
      layout="prev, pager, next, total"
      style="margin-top: 16px; justify-content: flex-end; display: flex"
    />

    <el-dialog v-model="showContent" title="通知内容" width="600px">
      <pre style="white-space: pre-wrap; font-size: 14px">{{ currentContent }}</pre>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { notificationApi } from '../api'

const logs = ref([])
const loading = ref(false)
const showContent = ref(false)
const currentContent = ref('')
const currentPage = ref(1)
const pageSize = 20
const pagedItems = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return logs.value.slice(start, start + pageSize)
})

async function loadLogs() {
  loading.value = true
  try {
    const data = await notificationApi.listLogs()
    logs.value = data.items
  } catch (e) {
    ElMessage.error('加载通知记录失败')
  } finally {
    loading.value = false
  }
}

function viewContent(row) {
  currentContent.value = row.content
  showContent.value = true
}

async function clearAll() {
  try {
    await ElMessageBox.prompt(
      '此操作将永久删除所有通知记录，且不可恢复。\n请输入「确认清空」以继续：',
      '危险操作',
      {
        confirmButtonText: '清空',
        cancelButtonText: '取消',
        type: 'error',
        inputValidator: (val) => val === '确认清空' || '请输入「确认清空」',
        inputPlaceholder: '确认清空'
      }
    )
    await notificationApi.clearAll()
    ElMessage.success('已清空')
    currentPage.value = 1
    loadLogs()
  } catch {
    /* cancelled */
  }
}

onMounted(loadLogs)
</script>
