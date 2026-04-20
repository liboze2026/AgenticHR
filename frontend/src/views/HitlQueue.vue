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
        <el-button type="warning" :loading="autoClassifying" @click="doAutoClassify"
                   v-if="hasPendingSkills">
          一键自动分类 ({{ pendingSkillCount }})
        </el-button>
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
          <template #default="{ row }">{{ taskTitle(row) }}</template>
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
            <el-button v-if="row.f_stage === 'F1_skill_classification' && row.status === 'pending'"
                       size="small" type="success" @click="openClassify(row)">归类</el-button>
            <el-button v-if="row.status === 'pending'" size="small" @click="quickApprove(row)">快速通过</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 技能归类弹窗 -->
    <el-dialog v-model="showClassifyDialog" title="技能归类" width="420px" :close-on-click-modal="false">
      <div class="classify-skill-name">
        <span class="label">技能名称：</span>
        <strong>{{ classifyRow?.payload?.name || `技能 #${classifyRow?.entity_id}` }}</strong>
      </div>
      <el-form label-width="80px" style="margin-top: 16px">
        <el-form-item label="分类">
          <el-select v-model="classifyCategory" placeholder="请选择分类" style="width: 100%">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showClassifyDialog = false">取消</el-button>
        <el-button type="primary" :loading="classifying"
                   :disabled="!classifyCategory" @click="doClassify">确认归类</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { hitlApi, skillsApi } from '../api'
import { refreshHitlCount } from '../stores/hitlState'

const autoClassifying = ref(false)
const hasPendingSkills = computed(() =>
  items.value.some(r => r.f_stage === 'F1_skill_classification' && r.status === 'pending')
)
const pendingSkillCount = computed(() =>
  items.value.filter(r => r.f_stage === 'F1_skill_classification' && r.status === 'pending').length
)

const router = useRouter()
const stageFilter = ref('')
const statusFilter = ref('pending')
const items = ref([])
const loading = ref(false)

const showClassifyDialog = ref(false)
const classifyRow = ref(null)
const classifyCategory = ref('')
const classifying = ref(false)
const categories = ref([])

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
  } catch (e) {
    ElMessage.error('加载审核队列失败，请稍后重试')
  } finally { loading.value = false }
}

async function loadCategories() {
  try {
    const resp = await skillsApi.categories()
    categories.value = resp.categories || []
  } catch {}
}

function openClassify(row) {
  classifyRow.value = row
  classifyCategory.value = ''
  showClassifyDialog.value = true
}

async function doClassify() {
  if (!classifyCategory.value) return
  classifying.value = true
  try {
    await skillsApi.update(classifyRow.value.entity_id, {
      category: classifyCategory.value,
      pending_classification: false,
    })
    await hitlApi.approve(classifyRow.value.id, `已归类: ${classifyCategory.value}`)
    ElMessage.success(`已将「${classifyRow.value.payload?.name}」归类为 ${classifyCategory.value}`)
    showClassifyDialog.value = false
    refresh()
    refreshHitlCount()
  } catch (e) {
    ElMessage.error('归类失败：' + (e.response?.data?.detail || e.message || '请重试'))
  } finally {
    classifying.value = false
  }
}

async function doAutoClassify() {
  autoClassifying.value = true
  try {
    const result = await skillsApi.autoClassify()
    ElMessage.success(`已自动归类 ${result.classified} 个技能（${result.method}）`)
    refresh()
    refreshHitlCount()
  } catch (e) {
    ElMessage.error('自动分类失败：' + (e.response?.data?.detail || e.message || '请重试'))
  } finally {
    autoClassifying.value = false
  }
}

function gotoJob(row) {
  router.push({ path: '/jobs', query: { id: row.entity_id, tab: 'competency' } })
}

async function quickApprove(row) {
  try {
    await ElMessageBox.confirm('确认快速通过?', '确认', { type: 'warning' })
    await hitlApi.approve(row.id, '快速通过')
    ElMessage.success('已通过')
    refresh()
    refreshHitlCount()
  } catch (e) {
    if (e !== 'cancel' && e?.type !== 'cancel') ElMessage.error('操作失败: ' + (e.message || e))
  }
}

onMounted(() => { refresh(); loadCategories() })
</script>

<style scoped>
.hitl-queue { padding: 20px; }
.filters { margin-bottom: 16px; display: flex; gap: 12px; flex-wrap: wrap; }
.classify-skill-name { font-size: 15px; padding: 4px 0; }
.classify-skill-name .label { color: #909399; }
</style>
