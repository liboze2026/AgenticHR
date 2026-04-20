<template>
  <div class="hitl-queue">
    <el-card>
      <div class="filters">
        <el-radio-group v-model="stageFilter" @change="refresh">
          <el-radio-button label="">全部</el-radio-button>
          <el-radio-button label="F1_competency_review">能力模型</el-radio-button>
          <el-radio-button label="F1_skill_classification">新技能</el-radio-button>
        </el-radio-group>
        <el-radio-group v-model="statusFilter" @change="refresh">
          <el-radio-button label="pending">待审</el-radio-button>
          <el-radio-button label="approved">已通过</el-radio-button>
          <el-radio-button label="rejected">已驳回</el-radio-button>
          <el-radio-button label="">全部</el-radio-button>
        </el-radio-group>
        <el-button @click="refresh">刷新</el-button>
      </div>

      <el-table :data="items" v-loading="loading" border>
        <el-table-column label="类型" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.f_stage === 'F1_competency_review'" type="primary">能力模型</el-tag>
            <el-tag v-else-if="row.f_stage === 'F1_skill_classification'" type="success">新技能</el-tag>
            <el-tag v-else>{{ row.f_stage }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="标题" min-width="200">
          <template #default="{ row }">
            <span>{{ taskTitle(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="160">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button v-if="row.f_stage === 'F1_competency_review'"
                       size="small" type="primary" @click="gotoJob(row)">审核</el-button>
            <el-button v-if="row.f_stage === 'F1_skill_classification'"
                       size="small" type="success" @click="gotoSkill(row)">归类</el-button>
            <el-button v-if="row.status === 'pending'" size="small" @click="quickApprove(row)">快速通过</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { hitlApi } from '../api'

const router = useRouter()
const stageFilter = ref('')
const statusFilter = ref('pending')
const items = ref([])
const loading = ref(false)

function taskTitle(row) {
  if (row.f_stage === 'F1_competency_review') return `岗位 #${row.entity_id}`
  if (row.f_stage === 'F1_skill_classification') return row.payload?.name || `新技能 #${row.entity_id}`
  return `${row.entity_type} #${row.entity_id}`
}

function formatTime(t) { return t ? new Date(t).toLocaleString() : '' }
function statusType(s) {
  return { pending: 'warning', approved: 'success', rejected: 'danger', edited: 'success' }[s] || 'info'
}
function statusText(s) {
  return { pending: '待审', approved: '已通过', rejected: '已驳回', edited: '已修改' }[s] || s
}

async function refresh() {
  loading.value = true
  try {
    const params = {}
    if (stageFilter.value) params.stage = stageFilter.value
    if (statusFilter.value) params.status = statusFilter.value
    const resp = await hitlApi.list(params)
    items.value = resp.items || []
  } finally { loading.value = false }
}

function gotoJob(row) {
  router.push({ path: '/jobs', query: { id: row.entity_id, tab: 'competency' } })
}
function gotoSkill(row) {
  router.push({ path: '/skills', query: { pending: 1, focus: row.entity_id } })
}

async function quickApprove(row) {
  try {
    await ElMessageBox.confirm('确认快速通过?', '确认', { type: 'warning' })
    await hitlApi.approve(row.id, '快速通过')
    ElMessage.success('已通过')
    refresh()
  } catch {}
}

onMounted(refresh)
</script>

<style scoped>
.hitl-queue { padding: 20px; }
.filters { margin-bottom: 16px; display: flex; gap: 12px; flex-wrap: wrap; }
</style>
