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
      <el-table-column label="能力模型" width="110">
        <template #default="{ row }">
          <el-tag v-if="extractingJobIds.has(row.id)" type="info" size="small">
            <el-icon style="vertical-align: middle; animation: rotating 1.5s linear infinite">
              <svg viewBox="0 0 1024 1024" width="12" height="12"><path fill="currentColor" d="M512 64a32 32 0 0 1 32 32v192a32 32 0 0 1-64 0V96a32 32 0 0 1 32-32zm0 640a32 32 0 0 1 32 32v192a32 32 0 0 1-64 0V736a32 32 0 0 1 32-32zm448-192a32 32 0 0 1-32 32H736a32 32 0 0 1 0-64h192a32 32 0 0 1 32 32zm-640 0a32 32 0 0 1-32 32H96a32 32 0 0 1 0-64h192a32 32 0 0 1 32 32zM195.2 195.2a32 32 0 0 1 45.248 0L376.32 331.008a32 32 0 0 1-45.248 45.248L195.2 240.448a32 32 0 0 1 0-45.248zm452.544 452.544a32 32 0 0 1 45.248 0L828.8 783.552a32 32 0 0 1-45.248 45.248L647.744 692.992a32 32 0 0 1 0-45.248zM828.8 195.2a32 32 0 0 1 0 45.248L692.992 376.32a32 32 0 0 1-45.248-45.248L783.552 195.2a32 32 0 0 1 45.248 0zm-452.544 452.544a32 32 0 0 1 0 45.248L240.448 828.8a32 32 0 0 1-45.248-45.248l135.808-135.808a32 32 0 0 1 45.248 0z"/></svg>
            </el-icon>
            抽取中…
          </el-tag>
          <el-tag v-else :type="competencyTagType(row.competency_model_status)" size="small">
            {{ competencyTagText(row.competency_model_status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '启用' : '停用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="240" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="editJob(row)">编辑</el-button>
          <el-button size="small" type="primary" @click="screenResumes(row.id)">筛选简历</el-button>
          <el-button size="small" type="danger" link @click="deleteJob(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 创建/编辑岗位弹窗 -->
    <el-dialog v-model="showCreateDialog" :title="editingJob ? '编辑岗位' : '新建岗位'" width="700px">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="基本信息" name="basic">
          <!-- Step 1: JD 输入（新建岗位时） -->
          <div v-if="parseStep === 'input'">
            <el-input
              v-model="jdInput"
              type="textarea"
              :rows="12"
              placeholder="粘贴岗位 JD 原文，系统将自动识别岗位名称、学历要求、薪资范围、必备技能等信息..."
            />
            <div style="margin-top: 12px; display: flex; gap: 8px; align-items: center">
              <el-button type="primary" @click="parseJd" :loading="parsing" :disabled="!jdInput.trim()">
                解析 JD
              </el-button>
              <el-button link @click="parseStep = 'review'">手动填写</el-button>
            </div>
          </div>

          <!-- Step 2: 表单（新建 review + 编辑） -->
          <div v-else>
            <el-button v-if="!editingJob" link @click="parseStep = 'input'" style="margin-bottom: 8px">
              ← 重新粘贴 JD
            </el-button>
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
                <el-input v-model="jobForm.soft_requirements" type="textarea" :rows="3" />
              </el-form-item>
              <el-form-item label="打招呼话术">
                <el-input v-model="jobForm.greeting_templates" type="textarea" :rows="2" placeholder="竖线分隔多条" />
              </el-form-item>
            </el-form>
          </div>
        </el-tab-pane>
        <el-tab-pane :label="competencyLabel" name="competency" v-if="currentJobId">
          <CompetencyEditor :job-id="currentJobId" :initial-jd-text="jobForm.jd_text || ''" @status-change="onStatusChange" @extract-background="onExtractBackground" />
        </el-tab-pane>
        <el-tab-pane label="匹配候选人" name="matching" v-if="editingJob && editingJob.competency_model_status === 'approved'">
          <div class="matching-toolbar">
            <el-button type="primary" plain @click="recomputeMatching" :loading="matching.recomputing">重新打分</el-button>
            <el-select v-model="matching.tagFilter" placeholder="按标签筛选" clearable @change="loadMatching" style="width: 180px; margin-left: 8px">
              <el-option label="高匹配" value="高匹配" />
              <el-option label="中匹配" value="中匹配" />
              <el-option label="低匹配" value="低匹配" />
              <el-option label="硬门槛未过" value="硬门槛未过" />
            </el-select>
            <span v-if="matching.staleCount > 0" class="stale-warn">
              ⚠ {{ matching.staleCount }} 份分数基于旧能力模型
            </span>
          </div>

          <div v-loading="matching.loading">
            <el-empty v-if="!matching.items.length" description="尚无匹配结果，发布能力模型后会自动打分" />

            <div v-for="item in matching.items" :key="item.id" class="matching-row" :class="{ expanded: matching.expandedId === item.id }">
              <div class="matching-head" @click="toggleMatchingExpand(item.id)">
                <span class="m-name">{{ item.resume_name }}</span>
                <span class="m-score">{{ item.total_score.toFixed(1) }}</span>
                <div class="m-tags">
                  <el-tag v-for="t in item.tags" :key="t" :type="tagType(t)" size="small">{{ t }}</el-tag>
                  <el-tag v-if="item.stale" type="warning" effect="plain" size="small">⚠ 过时</el-tag>
                </div>
              </div>

              <transition name="expand">
                <div v-if="matching.expandedId === item.id" class="matching-detail">
                  <div class="dim-bar" v-for="(dim, key) in dimensionList(item)" :key="key">
                    <span class="dim-label">{{ dim.label }} ({{ dim.weight }}%)</span>
                    <el-progress :percentage="dim.score" :color="dim.color" :stroke-width="16" />
                  </div>

                  <div v-if="item.hard_gate_passed === false" class="hard-gate-warn">
                    🛑 硬门槛未过：缺失必须项 {{ item.missing_must_haves.join(', ') }}
                  </div>

                  <div class="evidence-list">
                    <h4>证据片段</h4>
                    <div v-for="(items, dim) in item.evidence" :key="dim">
                      <div v-for="(e, i) in items" :key="i" class="evidence-item">
                        <span class="ev-dim">[{{ dim }}]</span>
                        <span class="ev-text">{{ e.text }}</span>
                        <el-button v-if="e.source && e.offset" link size="small" @click="jumpToResume(item.resume_id, e.source, e.offset)">查看原文</el-button>
                      </div>
                    </div>
                  </div>
                </div>
              </transition>
            </div>

            <el-pagination
              v-model:current-page="matching.page"
              :page-size="matching.pageSize"
              :total="matching.total"
              layout="total, prev, pager, next"
              @current-change="loadMatching"
              style="margin-top: 12px; justify-content: flex-end"
            />
          </div>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="saveJob" v-if="activeTab === 'basic' && parseStep === 'review'">保存</el-button>
      </template>
    </el-dialog>

    <!-- 筛选结果弹窗 -->
    <el-dialog v-model="showScreenResult" title="硬性条件筛选结果（仅供参考，不修改简历状态）" width="700px">
      <div v-if="screenResult">
        <p style="margin-bottom: 4px">共 {{ screenResult.total }} 份简历，通过 {{ screenResult.passed }}，未通过 {{ screenResult.rejected }}</p>
        <p style="margin-bottom: 12px; color: #909399; font-size: 12px">
          此筛选只是按本岗位的硬性条件做基础匹配；候选人的全局"在库 / 已归档"状态不会变。
          详细评分进岗位详情的"匹配候选人"Tab 看 F2 AI 评分。
        </p>
        <el-table :data="screenResult.results" max-height="400">
          <el-table-column prop="resume_name" label="姓名" width="120" />
          <el-table-column label="结果" width="80">
            <template #default="{ row }">
              <el-tag :type="row.passed ? 'success' : 'warning'" size="small">{{ row.passed ? '通过' : '未通过' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="原因">
            <template #default="{ row }">{{ row.reject_reasons?.join('; ') || '-' }}</template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>
    <!-- AI 评估弹窗已废弃 — F2 评分进入岗位详情看 "匹配候选人" Tab -->
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox, ElNotification } from 'element-plus'
import { jobApi, competencyApi, matchingApi } from '../api'
import CompetencyEditor from '../components/CompetencyEditor.vue'
import { extractingJobIds } from '../stores/extractingJobs.js'

const jobs = ref([])
const loading = ref(false)
const showCreateDialog = ref(false)
const editingJob = ref(null)
const showScreenResult = ref(false)
const screenResult = ref(null)
const aiLoading = ref(false)

const activeTab = ref('basic')
const currentJobId = ref(null)
const competencyStatus = ref('none')

// JD 解析相关
const jdInput = ref('')
const parseStep = ref('input')   // 'input' | 'review'
const parsing = ref(false)

const competencyLabel = computed(() => {
  if (competencyStatus.value === 'draft') return '能力模型 ●待审'
  if (competencyStatus.value === 'approved') return '能力模型 ✓'
  if (competencyStatus.value === 'rejected') return '能力模型 ✕'
  return '能力模型'
})

function onStatusChange(s) { competencyStatus.value = s }

function onExtractBackground({ jobId, jdText }) {
  showCreateDialog.value = false
  extractingJobIds.add(jobId)
  ElMessage.success('能力模型抽取中，完成后会通知您…')
  competencyApi.extract(jobId, jdText).then((result) => {
    extractingJobIds.delete(jobId)
    loadJobs()
    if (result?.status === 'failed') {
      ElNotification({ title: '能力模型抽取失败', message: '请重新进入岗位编辑页触发抽取', type: 'error', duration: 8000 })
    } else {
      ElNotification({ title: '能力模型已生成，待 HR 审核', message: '请前往「审核队列」完成审核后方可生效', type: 'warning', duration: 6000 })
    }
  }).catch(() => {
    extractingJobIds.delete(jobId)
    loadJobs()
    ElNotification({ title: '能力模型抽取失败', message: '请重新进入岗位编辑页触发抽取', type: 'error', duration: 8000 })
  })
}

function competencyTagType(status) {
  return { none: 'info', draft: 'warning', approved: 'success', rejected: 'danger' }[status] || 'info'
}
function competencyTagText(status) {
  return { none: '未生成', draft: '待审核', approved: '已生效', rejected: '已驳回' }[status] || '未知'
}

const defaultForm = { title: '', department: '', education_min: '', work_years_min: 0, work_years_max: 99, salary_min: 0, salary_max: 0, required_skills: '', soft_requirements: '', greeting_templates: '', jd_text: '' }
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
  jdInput.value = ''
  parseStep.value = 'input'    // 新建从第一步开始
  showCreateDialog.value = true
}

function editJob(job) {
  editingJob.value = job
  jobForm.value = { ...job }
  currentJobId.value = job.id
  activeTab.value = 'basic'
  parseStep.value = 'review'   // 编辑直接进表单
  showCreateDialog.value = true
}

async function parseJd() {
  if (!jdInput.value.trim()) { ElMessage.warning('请先粘贴 JD 原文'); return }
  parsing.value = true
  try {
    const result = await jobApi.parseJd(jdInput.value)
    // 预填表单
    jobForm.value = {
      title: result.title || '',
      department: result.department || '',
      education_min: result.education_min || '',
      work_years_min: result.work_years_min ?? 0,
      work_years_max: result.work_years_max ?? 99,
      salary_min: result.salary_min ?? 0,
      salary_max: result.salary_max ?? 0,
      required_skills: result.required_skills || '',
      soft_requirements: result.soft_requirements || '',
      greeting_templates: '',
      jd_text: jdInput.value,
    }
    parseStep.value = 'review'
  } catch (e) {
    ElMessage.error('解析失败：' + (e.message || e))
  } finally {
    parsing.value = false
  }
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
    let targetJobId = null
    let jdChanged = false
    if (editingJob.value) {
      // 检测 JD 是否变更（变更则需要重抽能力模型）
      jdChanged = (jobForm.value.jd_text || '').trim() !== (editingJob.value.jd_text || '').trim()
      await jobApi.update(editingJob.value.id, jobForm.value)
      ElMessage.success('更新成功')
      showCreateDialog.value = false
      targetJobId = editingJob.value.id
    } else {
      const created = await jobApi.create(jobForm.value)
      showCreateDialog.value = false
      targetJobId = created.id
      jdChanged = !!jobForm.value.jd_text?.trim()
    }
    loadJobs()
    // 自动触发抽取：新建有 JD，或编辑改了 JD
    if (targetJobId && jdChanged && jobForm.value.jd_text?.trim()) {
      extractingJobIds.add(targetJobId)
      ElMessage.success(editingJob.value ? 'JD 已变更，正在重抽能力模型…' : '岗位已创建，正在抽取能力模型…')
      competencyApi.extract(targetJobId, jobForm.value.jd_text).then((result) => {
        extractingJobIds.delete(targetJobId)
        loadJobs()
        if (result?.status === 'failed') {
          ElNotification({ title: '能力模型抽取失败', message: '请进入岗位编辑页手动触发抽取', type: 'error', duration: 8000 })
        } else {
          ElNotification({ title: '能力模型已生成，待 HR 审核', message: '请前往「审核队列」完成审核后方可生效', type: 'warning', duration: 6000 })
        }
      }).catch((e) => {
        extractingJobIds.delete(targetJobId)
        loadJobs()
        const msg = e?.code === 'ECONNABORTED' ? 'LLM 调用超时（>120s），请稍后到岗位编辑页重试' : '请进入岗位编辑页手动触发抽取'
        ElNotification({ title: '能力模型抽取失败', message: msg, type: 'error', duration: 8000 })
      })
    }
  } catch (e) {
    ElMessage.error('保存失败：' + (e.response?.data?.detail || e.message || '请重试'))
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

// AI 评估按钮已废弃 — F2 用 matchingApi.recomputeJob 在岗位详情 "匹配候选人" Tab 触发

async function screenResumes(jobId) {
  try {
    const result = await jobApi.screen(jobId)
    screenResult.value = result
    showScreenResult.value = true
    ElMessage.success(`筛选完成：通过 ${result.passed}，未通过 ${result.rejected}（简历状态未变更）`)
  } catch (e) {
    ElMessage.error('筛选失败')
  }
}

// ── 匹配候选人 Tab ──────────────────────────────────────────────────────────
const matching = ref({
  loading: false,
  items: [],
  total: 0,
  page: 1,
  pageSize: 20,
  tagFilter: '',
  expandedId: null,
  recomputing: false,
  staleCount: 0,
  pollTimer: null,
})

async function loadMatching() {
  if (!editingJob.value) return
  matching.value.loading = true
  try {
    const data = await matchingApi.listByJob(editingJob.value.id, {
      page: matching.value.page,
      page_size: matching.value.pageSize,
      tag: matching.value.tagFilter || undefined,
    })
    matching.value.items = data.items
    matching.value.total = data.total
    matching.value.staleCount = data.items.filter(i => i.stale).length
  } catch (e) {
    ElMessage.error('加载匹配候选人失败')
  } finally {
    matching.value.loading = false
  }
}

function toggleMatchingExpand(id) {
  matching.value.expandedId = matching.value.expandedId === id ? null : id
}

function dimensionList(item) {
  return [
    { label: '技能匹配', score: item.skill_score, weight: 35, color: scoreColor(item.skill_score) },
    { label: '工作经验', score: item.experience_score, weight: 30, color: scoreColor(item.experience_score) },
    { label: '职级对齐', score: item.seniority_score, weight: 15, color: scoreColor(item.seniority_score) },
    { label: '教育背景', score: item.education_score, weight: 10, color: scoreColor(item.education_score) },
    { label: '行业经验', score: item.industry_score, weight: 10, color: scoreColor(item.industry_score) },
  ]
}

function scoreColor(s) {
  if (s >= 80) return '#67c23a'
  if (s >= 60) return '#409eff'
  if (s >= 40) return '#e6a23c'
  return '#f56c6c'
}

function tagType(tag) {
  if (tag === '高匹配') return 'success'
  if (tag === '中匹配') return 'primary'
  if (tag === '低匹配') return 'warning'
  if (tag === '不匹配' || tag.startsWith('硬门槛') || tag.startsWith('必须项缺失-')) return 'danger'
  return 'info'
}

async function recomputeMatching() {
  if (!editingJob.value) return
  try {
    matching.value.recomputing = true
    const { task_id } = await matchingApi.recomputeJob(editingJob.value.id)
    matching.value.pollTimer = setInterval(async () => {
      const s = await matchingApi.recomputeStatus(task_id)
      if (!s.running) {
        clearInterval(matching.value.pollTimer)
        matching.value.pollTimer = null
        matching.value.recomputing = false
        ElMessage.success(`打分完成：${s.completed}/${s.total}`)
        loadMatching()
      }
    }, 2000)
  } catch (e) {
    matching.value.recomputing = false
    ElMessage.error('启动打分失败')
  }
}

function jumpToResume(resumeId, source, offset) {
  const [start, end] = offset
  window.open(`/#/resumes/${resumeId}?highlight=${start},${end}&source=${source}`, '_blank')
}

watch(activeTab, (tab) => {
  if (tab === 'matching' && editingJob.value) loadMatching()
})

onUnmounted(() => {
  if (matching.value.pollTimer) clearInterval(matching.value.pollTimer)
})

onMounted(loadJobs)
</script>

<style scoped>
@keyframes rotating {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}

.matching-toolbar {
  display: flex; gap: 8px; align-items: center;
  margin-bottom: 16px;
}
.stale-warn { color: #e6a23c; font-size: 13px; margin-left: 12px; }

.matching-row {
  border: 1px solid #ebeef5; border-radius: 6px;
  margin-bottom: 8px; overflow: hidden;
}
.matching-row.expanded { border-color: #409eff; }
.matching-head {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 16px; cursor: pointer;
  transition: background 0.1s;
}
.matching-head:hover { background: #f5f7fa; }
.m-name { font-weight: 600; min-width: 80px; }
.m-score { font-size: 20px; color: #409eff; font-weight: 700; min-width: 60px; }
.m-tags { display: flex; gap: 4px; flex-wrap: wrap; }

.matching-detail { padding: 12px 16px; background: #fafbfc; border-top: 1px solid #f0f2f5; }
.dim-bar { display: flex; align-items: center; gap: 12px; margin-bottom: 6px; }
.dim-label { width: 140px; font-size: 12px; color: #606266; }
.dim-bar :deep(.el-progress) { flex: 1; }

.hard-gate-warn {
  margin-top: 10px; padding: 8px 12px;
  background: #fef0f0; color: #c45656;
  border-radius: 4px; font-size: 13px;
}
.evidence-list { margin-top: 12px; }
.evidence-list h4 { margin: 6px 0; color: #606266; font-size: 13px; }
.evidence-item { display: flex; gap: 6px; align-items: center; font-size: 13px; margin: 3px 0; }
.ev-dim { color: #909399; font-size: 11px; min-width: 70px; }
.ev-text { flex: 1; }

.expand-enter-active, .expand-leave-active { transition: all 0.2s ease-out; overflow: hidden; }
.expand-enter-from, .expand-leave-to { max-height: 0; opacity: 0; }
.expand-enter-to, .expand-leave-from { max-height: 800px; opacity: 1; }
</style>
