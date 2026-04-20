<template>
  <div>
    <div style="display: flex; justify-content: space-between; margin-bottom: 16px">
      <h2>岗位管理</h2>
      <el-button type="primary" @click="openNewJob">新建岗位</el-button>
    </div>

    <el-table :data="jobs" stripe v-loading="loading">
      <el-table-column prop="title" label="岗位名称" />
      <el-table-column prop="department" label="部门" width="120" />
      <el-table-column prop="education_min" label="最低学历" width="100" />
      <el-table-column label="工作年限" width="120">
        <template #default="{ row }">{{ row.work_years_min }}-{{ row.work_years_max }}年</template>
      </el-table-column>
      <el-table-column prop="required_skills" label="必备技能" show-overflow-tooltip />
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '启用' : '停用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="300" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="editJob(row)">编辑</el-button>
          <el-button size="small" type="primary" @click="screenResumes(row.id)">筛选简历</el-button>
          <el-button size="small" type="warning" @click="aiEvaluate(row)" :loading="row._aiLoading">AI评估</el-button>
          <el-button size="small" type="danger" link @click="deleteJob(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 创建/编辑岗位弹窗 -->
    <el-dialog v-model="showCreateDialog" :title="editingJob ? '编辑岗位' : '新建岗位'" width="700px">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="基本信息" name="basic">
          <el-form :model="jobForm" label-width="100px">
            <el-form-item label="岗位名称" required>
              <el-input v-model="jobForm.title" />
            </el-form-item>
            <el-form-item label="部门">
              <el-input v-model="jobForm.department" />
            </el-form-item>
            <el-form-item label="最低学历">
              <el-select v-model="jobForm.education_min" clearable>
                <el-option label="大专" value="大专" />
                <el-option label="本科" value="本科" />
                <el-option label="硕士" value="硕士" />
                <el-option label="博士" value="博士" />
              </el-select>
            </el-form-item>
            <el-form-item label="工作年限">
              <el-col :span="11">
                <el-input-number v-model="jobForm.work_years_min" :min="0" />
              </el-col>
              <el-col :span="2" style="text-align: center">-</el-col>
              <el-col :span="11">
                <el-input-number v-model="jobForm.work_years_max" :min="0" />
              </el-col>
            </el-form-item>
            <el-form-item label="薪资范围">
              <el-col :span="11">
                <el-input-number v-model="jobForm.salary_min" :min="0" :step="1000" />
              </el-col>
              <el-col :span="2" style="text-align: center">-</el-col>
              <el-col :span="11">
                <el-input-number v-model="jobForm.salary_max" :min="0" :step="1000" />
              </el-col>
            </el-form-item>
            <el-form-item label="必备技能">
              <el-input v-model="jobForm.required_skills" placeholder="逗号分隔，如 Python,FastAPI" />
            </el-form-item>
            <el-form-item label="软性要求">
              <el-input v-model="jobForm.soft_requirements" type="textarea" :rows="3" placeholder="自然语言描述，如：有大厂经历优先" />
            </el-form-item>
            <el-form-item label="打招呼话术">
              <el-input v-model="jobForm.greeting_templates" type="textarea" :rows="2" placeholder="竖线分隔多条，如：你好请发简历|您好方便发简历吗" />
            </el-form-item>
          </el-form>
        </el-tab-pane>
        <el-tab-pane :label="competencyLabel" name="competency" v-if="currentJobId">
          <CompetencyEditor :job-id="currentJobId" @status-change="onStatusChange" />
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="saveJob" v-if="activeTab === 'basic'">保存</el-button>
      </template>
    </el-dialog>

    <!-- 筛选结果弹窗 -->
    <el-dialog v-model="showScreenResult" title="筛选结果" width="700px">
      <div v-if="screenResult">
        <p style="margin-bottom: 12px">共 {{ screenResult.total }} 份简历，通过 {{ screenResult.passed }}，淘汰 {{ screenResult.rejected }}</p>
        <el-table :data="screenResult.results" max-height="400">
          <el-table-column prop="resume_name" label="姓名" width="120" />
          <el-table-column label="结果" width="80">
            <template #default="{ row }">
              <el-tag :type="row.passed ? 'success' : 'danger'" size="small">{{ row.passed ? '通过' : '淘汰' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="原因">
            <template #default="{ row }">{{ row.reject_reasons?.join('; ') || '-' }}</template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>
    <!-- AI评估结果弹窗 -->
    <el-dialog v-model="showAiResult" title="AI 岗位匹配评估" width="800px">
      <div v-if="aiResult">
        <p style="margin-bottom: 12px">共评估 {{ aiResult.total }} 人，成功 {{ aiResult.succeeded }}，失败 {{ aiResult.failed }}</p>
        <el-table :data="aiResult.results" max-height="500">
          <el-table-column prop="resume_name" label="姓名" width="100" />
          <el-table-column label="评分" width="80" sortable :sort-by="row => row.score">
            <template #default="{ row }">
              <span :style="{ color: row.score >= 70 ? '#52c41a' : row.score >= 40 ? '#faad14' : '#ff4d4f', fontWeight: 'bold' }">
                {{ row.score >= 0 ? row.score : '-' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="建议" width="80">
            <template #default="{ row }">
              <el-tag :type="row.recommendation === '推荐' ? 'success' : row.recommendation === '待定' ? 'warning' : 'danger'" size="small">
                {{ row.recommendation }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="优势">
            <template #default="{ row }">{{ row.strengths?.join('、') || '-' }}</template>
          </el-table-column>
          <el-table-column label="风险">
            <template #default="{ row }">{{ row.risks?.join('、') || '-' }}</template>
          </el-table-column>
          <el-table-column prop="summary" label="综合评价" show-overflow-tooltip />
        </el-table>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { jobApi, aiApi } from '../api'
import CompetencyEditor from '../components/CompetencyEditor.vue'

const jobs = ref([])
const loading = ref(false)
const showCreateDialog = ref(false)
const editingJob = ref(null)
const showScreenResult = ref(false)
const screenResult = ref(null)
const showAiResult = ref(false)
const aiResult = ref(null)
const aiLoading = ref(false)

const activeTab = ref('basic')
const currentJobId = ref(null)
const competencyStatus = ref('none')

const competencyLabel = computed(() => {
  if (competencyStatus.value === 'draft') return '能力模型 ●待审'
  if (competencyStatus.value === 'approved') return '能力模型 ✓'
  if (competencyStatus.value === 'rejected') return '能力模型 ✕'
  return '能力模型'
})

function onStatusChange(s) { competencyStatus.value = s }

const defaultForm = { title: '', department: '', education_min: '', work_years_min: 0, work_years_max: 99, salary_min: 0, salary_max: 0, required_skills: '', soft_requirements: '', greeting_templates: '' }
const jobForm = ref({ ...defaultForm })

async function loadJobs() {
  loading.value = true
  try {
    const data = await jobApi.list()
    jobs.value = data.items
  } catch (e) {
    ElMessage.error('加载岗位失败')
  } finally {
    loading.value = false
  }
}

function openNewJob() {
  editingJob.value = null
  jobForm.value = { ...defaultForm }
  currentJobId.value = null
  activeTab.value = 'basic'
  showCreateDialog.value = true
}

function editJob(job) {
  editingJob.value = job
  jobForm.value = { ...job }
  currentJobId.value = job.id
  activeTab.value = 'basic'
  showCreateDialog.value = true
}

async function saveJob() {
  const form = jobForm.value
  if (!form.title?.trim()) { ElMessage.warning('请填写岗位名称'); return }
  if (form.work_years_min != null && form.work_years_max != null && form.work_years_max < form.work_years_min) {
    ElMessage.warning('最大工作年限不能小于最小工作年限'); return
  }
  if (form.salary_min != null && form.salary_max != null && form.salary_max > 0 && form.salary_max < form.salary_min) {
    ElMessage.warning('最高薪资不能低于最低薪资'); return
  }
  try {
    if (editingJob.value) {
      await jobApi.update(editingJob.value.id, jobForm.value)
      ElMessage.success('更新成功')
    } else {
      await jobApi.create(jobForm.value)
      ElMessage.success('创建成功')
    }
    showCreateDialog.value = false
    editingJob.value = null
    jobForm.value = { ...defaultForm }
    loadJobs()
  } catch (e) {
    ElMessage.error('保存失败')
  }
}

async function deleteJob(id) {
  try {
    await ElMessageBox.confirm('确定删除该岗位？', '确认')
    await jobApi.delete(id)
    ElMessage.success('已删除')
    loadJobs()
  } catch (e) {
    if (e === 'cancel') return
    if (e.response?.status === 409) {
      ElMessage.warning(e.response.data.detail)
    } else {
      ElMessage.error('删除失败')
    }
  }
}

async function aiEvaluate(row) {
  row._aiLoading = true
  try {
    const timeoutPromise = new Promise((_, reject) =>
      setTimeout(() => reject(new Error('timeout')), 60000)
    )
    const result = await Promise.race([aiApi.batchEvaluate({ job_id: row.id }), timeoutPromise])
    aiResult.value = result
    showAiResult.value = true
    ElMessage.success(`AI评估完成：${result.succeeded} 人`)
  } catch (e) {
    if (e.message === 'timeout') {
      ElMessage.warning('AI评估超时，请稍后重试')
    } else {
      ElMessage.error(e.response?.data?.detail || 'AI评估失败，请检查AI配置')
    }
  } finally {
    row._aiLoading = false
  }
}

async function screenResumes(jobId) {
  try {
    const result = await jobApi.screen(jobId)
    screenResult.value = result
    showScreenResult.value = true
    ElMessage.success(`筛选完成：通过 ${result.passed}，淘汰 ${result.rejected}`)
  } catch (e) {
    ElMessage.error('筛选失败')
  }
}

onMounted(loadJobs)
</script>
