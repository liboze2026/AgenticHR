<template>
  <div>
    <div style="display: flex; justify-content: space-between; margin-bottom: 16px">
      <h2>岗位管理</h2>
      <el-button type="primary" @click="openNewJob">新建岗位</el-button>
    </div>

    <el-table :data="jobs" stripe v-loading="loading">
      <el-table-column prop="title" label="岗位名称" min-width="140" />
      <el-table-column prop="department" label="部门" width="90" />
      <el-table-column prop="education_min" label="最低学历" width="80" />
      <el-table-column label="工作年限" width="95">
        <template #default="{ row }">{{ row.work_years_min }}-{{ row.work_years_max }}年</template>
      </el-table-column>
      <el-table-column prop="required_skills" label="必备技能" min-width="140" show-overflow-tooltip />
      <el-table-column label="能力模型" width="95">
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
      <el-table-column label="状态" width="70">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '启用' : '停用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="230">
        <template #default="{ row }">
          <div style="display: flex; gap: 4px; flex-wrap: nowrap;">
            <el-button size="small" @click="editJob(row)">编辑</el-button>
            <el-button size="small" type="primary" @click="screenResumes(row.id)">筛选</el-button>
            <el-button size="small" type="danger" link @click="deleteJob(row.id)">删除</el-button>
          </div>
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
              <el-form-item label="JD 原文">
                <el-input v-model="jobForm.jd_text" type="textarea" :rows="5"
                          placeholder="岗位描述原文（可编辑，保存后自动重新抽取能力模型）" />
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
            <el-button
              type="default"
              plain
              size="small"
              style="margin-left: auto"
              @click="weightsPanel.open = !weightsPanel.open"
            >{{ weightsPanel.open ? '收起权重' : '评分权重' }}</el-button>
          </div>

          <!-- 评分权重面板 -->
          <div v-if="weightsPanel.open" class="weights-panel">
            <div class="weights-status">
              <span v-if="weightsPanel.custom" class="weights-status-custom">✓ 当前使用：本岗位自定义权重</span>
              <span v-else class="weights-status-global">○ 当前使用：全局默认权重（可在设置页修改）</span>
            </div>
            <div class="weights-inputs">
              <div class="weights-field" v-for="f in weightsFields" :key="f.key">
                <label>{{ f.label }}</label>
                <el-input-number
                  v-model="weightsPanel.form[f.key]"
                  :min="0"
                  :max="100"
                  size="small"
                  style="width: 100px"
                  @change="weightsPanel.dirty = true"
                />
              </div>
            </div>
            <div class="weights-sum-hint" :class="{ 'weights-sum-error': weightsSum !== 100 }">
              当前总和: {{ weightsSum }}（需为 100）
            </div>
            <div class="weights-actions">
              <el-button
                type="primary"
                size="small"
                :disabled="weightsSum !== 100"
                :loading="weightsPanel.saving"
                @click="saveJobWeights"
              >保存并重新打分</el-button>
              <el-button
                size="small"
                :loading="weightsPanel.resetting"
                @click="resetJobWeights"
              >重置为全局默认</el-button>
            </div>
          </div>

          <div v-loading="matching.loading">
            <el-empty v-if="!matching.items.length" description="尚无匹配结果，发布能力模型后会自动打分" />

            <div v-for="item in matching.items" :key="item.id" class="matching-row" :class="{ expanded: matching.expandedId === item.id }">
              <div class="matching-head">
                <div class="m-head-left" @click="toggleMatchingExpand(item.id)">
                  <el-icon class="m-arrow"><ArrowRight /></el-icon>
                  <span class="m-name">{{ item.resume_name }}</span>
                  <span class="m-score">{{ item.total_score.toFixed(1) }}</span>
                  <div class="m-tags">
                    <el-tag v-for="t in item.tags" :key="t" :type="tagType(t)" size="small">{{ t }}</el-tag>
                    <el-tag v-if="item.stale" type="warning" effect="plain" size="small">⚠ 过时</el-tag>
                    <el-tag v-if="item.job_action === 'passed'" type="success" size="small" effect="dark">本岗位通过</el-tag>
                    <el-tag v-else-if="item.job_action === 'rejected'" type="danger" size="small" effect="dark">本岗位淘汰</el-tag>
                  </div>
                </div>
                <div class="m-head-actions" @click.stop>
                  <el-button
                    :type="item.job_action === 'passed' ? 'success' : 'default'"
                    size="small"
                    @click="setJobAction(item, 'passed')"
                    :loading="item._actionLoading"
                  >{{ item.job_action === 'passed' ? '✓ 通过' : '通过' }}</el-button>
                  <el-button
                    :type="item.job_action === 'rejected' ? 'danger' : 'default'"
                    size="small"
                    @click="setJobAction(item, 'rejected')"
                    :loading="item._actionLoading"
                  >{{ item.job_action === 'rejected' ? '✕ 淘汰' : '淘汰' }}</el-button>
                  <el-button
                    v-if="item.job_action"
                    size="small"
                    link
                    @click="setJobAction(item, null)"
                    :loading="item._actionLoading"
                  >清除</el-button>
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

    <!-- 旧的硬筛 / AI 评估弹窗已废弃，改为 "筛选简历" 直接打开 "匹配候选人" Tab -->
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox, ElNotification } from 'element-plus'
import { ArrowRight } from '@element-plus/icons-vue'
import { jobApi, competencyApi, matchingApi, weightsApi } from '../api'
import CompetencyEditor from '../components/CompetencyEditor.vue'
import { extractingJobIds } from '../stores/extractingJobs.js'

const jobs = ref([])
const loading = ref(false)
const showCreateDialog = ref(false)
const editingJob = ref(null)
// const showScreenResult / screenResult 已移除 — "筛选简历" 现在直接打开匹配候选人 Tab
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
    if (result.parse_success === false) {
      ElMessage.error('大模型解析失败，请手动填写岗位信息或检查 AI 配置')
    }
    // 预填表单（parse_success=false 时 jd_text 仍保留，其余字段为空需手填）
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

// "筛选简历" 现在直接进入岗位详情的 "匹配候选人" Tab，让 HR 立刻能 通过/淘汰
function screenResumes(jobId) {
  const job = jobs.value.find(j => j.id === jobId)
  if (!job) {
    ElMessage.error('岗位未找到')
    return
  }
  if (job.competency_model_status !== 'approved') {
    ElMessage.warning('请先发布该岗位的能力模型，才能查看 AI 匹配候选人')
    editJob(job)
    return
  }
  // 走 editJob 流程，但 activeTab 直接定位到 matching
  editingJob.value = job
  jobForm.value = { ...job }
  currentJobId.value = job.id
  activeTab.value = 'matching'
  parseStep.value = 'review'
  showCreateDialog.value = true
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

// ── 评分权重面板 ────────────────────────────────────────────────────────────
const weightsFields = [
  { key: 'skill_match', label: '技能匹配' },
  { key: 'experience', label: '工作经验' },
  { key: 'seniority', label: '职级对齐' },
  { key: 'education', label: '教育背景' },
  { key: 'industry', label: '行业经验' },
]

const weightsPanel = ref({
  open: false,
  custom: false,
  saving: false,
  resetting: false,
  dirty: false,
  form: { skill_match: 35, experience: 30, seniority: 15, education: 10, industry: 10 },
})

const weightsSum = computed(() => {
  const f = weightsPanel.value.form
  return (f.skill_match || 0) + (f.experience || 0) + (f.seniority || 0) + (f.education || 0) + (f.industry || 0)
})

async function loadJobWeights() {
  if (!editingJob.value) return
  try {
    const data = await weightsApi.getJobWeights(editingJob.value.id)
    weightsPanel.value.custom = data.custom
    weightsPanel.value.form = { ...data.weights }
    weightsPanel.value.dirty = false
  } catch (_e) {
    // non-fatal: fall back to defaults
  }
}

async function saveJobWeights() {
  if (!editingJob.value) return
  if (weightsSum.value !== 100) { ElMessage.warning('权重总和必须为 100'); return }
  weightsPanel.value.saving = true
  try {
    await weightsApi.setJobWeights(editingJob.value.id, weightsPanel.value.form)
    weightsPanel.value.custom = true
    weightsPanel.value.dirty = false
    ElMessage.success('自定义权重已保存，正在重新打分…')
    await recomputeMatching()
    await loadJobWeights()
  } catch (e) {
    ElMessage.error('保存失败：' + (e.response?.data?.detail || e.message || '请重试'))
  } finally {
    weightsPanel.value.saving = false
  }
}

async function resetJobWeights() {
  if (!editingJob.value) return
  weightsPanel.value.resetting = true
  try {
    await weightsApi.resetJobWeights(editingJob.value.id)
    ElMessage.success('已恢复全局默认权重')
    await loadJobWeights()
    loadMatching()
  } catch (e) {
    ElMessage.error('重置失败：' + (e.message || '请重试'))
  } finally {
    weightsPanel.value.resetting = false
  }
}

function jobActionOrder(action) {
  if (action === 'passed') return 0
  if (action == null) return 1
  return 2  // 'rejected'
}

async function loadMatching() {
  if (!editingJob.value) return
  matching.value.loading = true
  try {
    const data = await matchingApi.listByJob(editingJob.value.id, {
      page: matching.value.page,
      page_size: matching.value.pageSize,
      tag: matching.value.tagFilter || undefined,
    })
    // Sort: passed first, then unevaluated, then rejected; within each group by total_score desc
    const sorted = [...data.items].sort((a, b) => {
      const ao = jobActionOrder(a.job_action)
      const bo = jobActionOrder(b.job_action)
      if (ao !== bo) return ao - bo
      return b.total_score - a.total_score
    })
    matching.value.items = sorted
    matching.value.total = data.total
    matching.value.staleCount = data.items.filter(i => i.stale).length
  } catch (e) {
    ElMessage.error('加载匹配候选人失败')
  } finally {
    matching.value.loading = false
  }
}

async function setJobAction(item, action) {
  if (item._actionLoading) return
  if (action === 'rejected' && item.job_action !== 'rejected') {
    try {
      await ElMessageBox.confirm(
        `确定将 "${item.resume_name}" 在本岗位标记为淘汰？不影响该候选人的全局状态。`,
        '确认淘汰',
        { type: 'warning', confirmButtonText: '确认', cancelButtonText: '取消' }
      )
    } catch { return }
  }
  item._actionLoading = true
  try {
    await matchingApi.setAction(item.id, action)
    item.job_action = action
    ElMessage.success(action === 'passed' ? '已标记本岗位通过' : action === 'rejected' ? '已标记本岗位淘汰' : '已清除本岗位决策')
    // Re-sort after action change
    const sorted = [...matching.value.items].sort((a, b) => {
      const ao = jobActionOrder(a.job_action)
      const bo = jobActionOrder(b.job_action)
      if (ao !== bo) return ao - bo
      return b.total_score - a.total_score
    })
    matching.value.items = sorted
  } catch (e) {
    ElMessage.error('操作失败')
  } finally {
    item._actionLoading = false
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
  if (tab === 'matching' && editingJob.value) {
    loadMatching()
    loadJobWeights()
    weightsPanel.value.open = false
  }
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
  padding: 10px 16px;
  transition: background 0.1s;
}
.m-head-left {
  flex: 1; display: flex; align-items: center; gap: 12px;
  cursor: pointer; min-width: 0;
}
.m-head-left:hover { opacity: 0.85; }
.m-arrow {
  font-size: 12px; color: #909399; transition: transform 0.2s; flex-shrink: 0;
}
.matching-row.expanded .m-arrow { transform: rotate(90deg); color: #409eff; }
.m-head-actions {
  display: flex; gap: 4px; align-items: center; flex-shrink: 0;
}
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

.job-action-bar {
  display: flex; align-items: center; gap: 8px;
  margin-top: 14px; padding-top: 10px;
  border-top: 1px dashed #e8e8e8;
}
.job-action-label { font-size: 12px; color: #909399; }

.expand-enter-active, .expand-leave-active { transition: all 0.2s ease-out; overflow: hidden; }
.expand-enter-from, .expand-leave-to { max-height: 0; opacity: 0; }
.expand-enter-to, .expand-leave-from { max-height: 800px; opacity: 1; }

/* 评分权重面板 */
.weights-panel {
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  background: #fafbfc;
  padding: 14px 16px;
  margin-bottom: 14px;
}
.weights-status { margin-bottom: 10px; font-size: 13px; }
.weights-status-custom { color: #67c23a; font-weight: 600; }
.weights-status-global { color: #909399; }
.weights-inputs {
  display: flex; flex-wrap: wrap; gap: 12px 24px;
  margin-bottom: 8px;
}
.weights-field {
  display: flex; align-items: center; gap: 6px;
}
.weights-field label { font-size: 12px; color: #606266; min-width: 60px; }
.weights-sum-hint {
  font-size: 12px; color: #909399; margin-bottom: 10px;
}
.weights-sum-error { color: #f56c6c; font-weight: 600; }
.weights-actions { display: flex; gap: 8px; }
</style>
