<template>
  <div class="ce">
    <!-- 顶部栏：状态 + 操作 -->
    <div class="ce-topbar">
      <div class="ce-status-badge" :class="status">
        <span class="dot"></span>
        {{ statusText(status) }}
      </div>
      <div class="ce-topbar-actions">
        <el-button v-if="model && !editMode" size="small" @click="editMode = true">编辑</el-button>
        <el-button v-if="editMode" size="small" @click="editMode = false">查看</el-button>
        <el-button size="small" :type="showJd ? '' : 'primary'"
                   @click="showJd = !showJd">
          {{ showJd ? '收起 JD' : (status === 'none' || status === 'rejected') ? '粘贴 JD 抽取' : '重新抽取' }}
        </el-button>
        <template v-if="model">
          <el-button size="small" @click="saveDraft" :loading="saving">保存草稿</el-button>
          <el-button size="small" type="primary" @click="submitApprove" :loading="saving">通过发布</el-button>
        </template>
      </div>
    </div>

    <!-- JD 输入区（折叠） -->
    <transition name="slide">
      <div v-if="showJd" class="ce-jd-box">
        <el-input v-model="jdText" type="textarea" :rows="6"
                  placeholder="粘贴岗位 JD 原文，点击「开始抽取」自动生成能力模型..." />
        <div class="ce-jd-footer">
          <el-button type="primary" :disabled="!jdText.trim()" @click="onExtract">开始抽取</el-button>
          <el-button @click="showJd = false">取消</el-button>
        </div>
      </div>
    </transition>

    <!-- 空状态 -->
    <div v-if="!model && !showJd" class="ce-empty">
      <div class="ce-empty-icon">📋</div>
      <p>暂无能力模型</p>
      <el-button type="primary" @click="showJd = true">粘贴 JD 开始抽取</el-button>
    </div>

    <!-- ── 查看模式 ── -->
    <template v-if="model && !editMode">
      <!-- 概要数字 -->
      <div class="ce-stats">
        <div class="ce-stat-item">
          <span class="ce-stat-n">{{ model.hard_skills.length }}</span>
          <span class="ce-stat-l">硬技能</span>
        </div>
        <div class="ce-stat-item">
          <span class="ce-stat-n">{{ model.soft_skills.length }}</span>
          <span class="ce-stat-l">软素质</span>
        </div>
        <div class="ce-stat-item">
          <span class="ce-stat-n">{{ model.experience.years_min }}+</span>
          <span class="ce-stat-l">年经验</span>
        </div>
        <div class="ce-stat-item">
          <span class="ce-stat-n">{{ model.education.min_level }}</span>
          <span class="ce-stat-l">最低学历</span>
        </div>
        <div v-if="model.job_level" class="ce-stat-item">
          <span class="ce-stat-n">{{ model.job_level }}</span>
          <span class="ce-stat-l">职级</span>
        </div>
      </div>

      <!-- 硬技能 -->
      <div class="ce-section">
        <div class="ce-section-hd">硬技能要求</div>
        <div class="ce-skill-grid">
          <div v-for="(s, i) in model.hard_skills" :key="i"
               class="ce-skill-card" :class="'level-' + s.level">
            <div class="ce-skill-name">{{ s.name }}</div>
            <div class="ce-skill-meta">
              <span class="ce-level-tag">{{ s.level }}</span>
              <span v-if="s.must_have" class="ce-must-tag">必须</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 软技能 -->
      <div v-if="model.soft_skills.length" class="ce-section">
        <div class="ce-section-hd">软性素质</div>
        <div class="ce-tag-row">
          <el-tag v-for="(s, i) in model.soft_skills" :key="i"
                  type="info" size="small" class="ce-soft-tag">
            {{ s.name }}
            <span class="ce-soft-stage">{{ s.assessment_stage }}</span>
          </el-tag>
        </div>
      </div>

      <!-- 经验 & 学历 -->
      <div class="ce-section ce-two-col">
        <div class="ce-info-block">
          <div class="ce-section-hd">经验要求</div>
          <div class="ce-info-row">
            <span class="lbl">年限</span>
            <span>{{ model.experience.years_min }} ~ {{ model.experience.years_max ?? '不限' }} 年</span>
          </div>
          <div v-if="model.experience.industries?.length" class="ce-info-row">
            <span class="lbl">行业</span>
            <span>{{ model.experience.industries.join('、') }}</span>
          </div>
          <div v-if="model.experience.company_scale" class="ce-info-row">
            <span class="lbl">规模</span>
            <span>{{ model.experience.company_scale }}</span>
          </div>
        </div>
        <div class="ce-info-block">
          <div class="ce-section-hd">学历要求</div>
          <div class="ce-info-row">
            <span class="lbl">最低</span>
            <span>{{ model.education.min_level }}</span>
          </div>
          <div v-if="model.education.preferred_level" class="ce-info-row">
            <span class="lbl">偏好</span>
            <span>{{ model.education.preferred_level }}</span>
          </div>
          <div class="ce-info-row">
            <span class="lbl">名校</span>
            <span>{{ model.education.prestigious_bonus ? '加分' : '不要求' }}</span>
          </div>
        </div>
      </div>

      <!-- 加分项 / 淘汰项 -->
      <div v-if="model.bonus_items.length || model.exclusions.length" class="ce-section ce-two-col">
        <div v-if="model.bonus_items.length" class="ce-info-block">
          <div class="ce-section-hd">加分项</div>
          <div class="ce-tag-row">
            <el-tag v-for="(b, i) in model.bonus_items" :key="i" type="success" size="small">{{ b }}</el-tag>
          </div>
        </div>
        <div v-if="model.exclusions.length" class="ce-info-block">
          <div class="ce-section-hd">淘汰项</div>
          <div class="ce-tag-row">
            <el-tag v-for="(e, i) in model.exclusions" :key="i" type="danger" size="small">{{ e }}</el-tag>
          </div>
        </div>
      </div>

      <!-- 考察维度 -->
      <div v-if="model.assessment_dimensions.length" class="ce-section">
        <div class="ce-section-hd">考察维度</div>
        <div class="ce-dimension-list">
          <div v-for="(d, i) in model.assessment_dimensions" :key="i" class="ce-dimension-item">
            <div class="ce-dim-header">
              <span class="ce-dim-index">{{ i + 1 }}</span>
              <span class="ce-dim-name">{{ d.name }}</span>
              <el-tag v-for="(q, qi) in d.question_types" :key="qi" size="small" type="warning" style="margin-left:4px">{{ q }}</el-tag>
            </div>
            <div v-if="d.description" class="ce-dim-desc">{{ d.description }}</div>
          </div>
        </div>
      </div>
    </template>

    <!-- ── 编辑模式 ── -->
    <template v-if="model && editMode">
      <el-collapse v-model="activeCards" class="ce-edit-collapse">
        <el-collapse-item title="硬技能" name="hard">
          <el-table :data="model.hard_skills" border size="small">
            <el-table-column label="技能" min-width="160">
              <template #default="{ row }">
                <SkillPicker v-model="row.name" @select="onSkillSelect(row, $event)" />
              </template>
            </el-table-column>
            <el-table-column label="等级" width="110">
              <template #default="{ row }">
                <el-select v-model="row.level" size="small">
                  <el-option label="了解" value="了解" /><el-option label="熟练" value="熟练" /><el-option label="精通" value="精通" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="必须" width="65" align="center">
              <template #default="{ row }"><el-checkbox v-model="row.must_have" /></template>
            </el-table-column>
            <el-table-column width="50">
              <template #default="{ $index }">
                <el-button size="small" type="danger" link @click="model.hard_skills.splice($index, 1)">删</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-button size="small" @click="model.hard_skills.push({ name: '', level: '熟练', weight: 5, must_have: false })" class="ce-add-btn">+ 添加技能</el-button>
        </el-collapse-item>

        <el-collapse-item title="软技能" name="soft">
          <div class="ce-soft-edit">
            <div v-for="(s, i) in model.soft_skills" :key="i" class="ce-soft-row">
              <el-input v-model="s.name" size="small" style="width:160px" />
              <el-select v-model="s.assessment_stage" size="small" style="width:90px">
                <el-option label="简历" value="简历" /><el-option label="IM" value="IM" /><el-option label="面试" value="面试" />
              </el-select>
              <el-button size="small" type="danger" link @click="model.soft_skills.splice(i, 1)">删</el-button>
            </div>
          </div>
          <el-button size="small" @click="model.soft_skills.push({ name: '', weight: 5, assessment_stage: '面试' })" class="ce-add-btn">+ 添加软技能</el-button>
        </el-collapse-item>

        <el-collapse-item title="经验 & 学历" name="exp">
          <el-form :model="model" label-width="90px" size="small">
            <el-form-item label="经验年限">
              <el-input-number v-model="model.experience.years_min" :min="0" :max="30" />
              <span style="margin:0 8px">~</span>
              <el-input-number v-model="model.experience.years_max" :min="0" :max="99" />
              <el-checkbox :model-value="model.experience.years_max === null"
                           @update:model-value="v => model.experience.years_max = v ? null : 99"
                           style="margin-left:8px">不限</el-checkbox>
            </el-form-item>
            <el-form-item label="最低学历">
              <el-radio-group v-model="model.education.min_level">
                <el-radio-button label="大专" /><el-radio-button label="本科" /><el-radio-button label="硕士" /><el-radio-button label="博士" />
              </el-radio-group>
            </el-form-item>
            <el-form-item label="名校加分">
              <el-switch v-model="model.education.prestigious_bonus" />
            </el-form-item>
          </el-form>
        </el-collapse-item>

        <el-collapse-item title="加分项 / 淘汰项" name="bonus">
          <div class="ce-tag-edit-row">
            <span class="lbl2">加分项</span>
            <el-tag v-for="(b, i) in model.bonus_items" :key="i" closable @close="model.bonus_items.splice(i,1)" type="success" size="small">{{ b }}</el-tag>
            <el-input v-model="newBonus" size="small" @keyup.enter="addBonus" placeholder="回车添加" style="width:140px" />
          </div>
          <div class="ce-tag-edit-row" style="margin-top:8px">
            <span class="lbl2">淘汰项</span>
            <el-tag v-for="(e, i) in model.exclusions" :key="i" closable @close="model.exclusions.splice(i,1)" type="danger" size="small">{{ e }}</el-tag>
            <el-input v-model="newExcl" size="small" @keyup.enter="addExcl" placeholder="回车添加" style="width:140px" />
          </div>
        </el-collapse-item>
      </el-collapse>
    </template>

    <!-- 降级手填 -->
    <template v-if="fallbackMode">
      <el-alert type="warning" :closable="false" title="LLM 抽取失败，请手工填写关键信息" show-icon style="margin:12px 0" />
      <el-form :model="flatForm" label-width="100px" size="small">
        <el-form-item label="最低学历">
          <el-select v-model="flatForm.education_min">
            <el-option label="大专" value="大专" /><el-option label="本科" value="本科" /><el-option label="硕士" value="硕士" /><el-option label="博士" value="博士" />
          </el-select>
        </el-form-item>
        <el-form-item label="工作年限">
          <el-input-number v-model="flatForm.work_years_min" :min="0" :max="30" />
          <span style="margin:0 6px">~</span>
          <el-input-number v-model="flatForm.work_years_max" :min="0" :max="30" />
        </el-form-item>
        <el-form-item label="必备技能">
          <el-input v-model="flatForm.required_skills" placeholder="Python,FastAPI,..." />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="submitFlat">保存并发布</el-button>
          <el-button @click="fallbackMode = false">取消</el-button>
        </el-form-item>
      </el-form>
    </template>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { competencyApi } from '../api'
import SkillPicker from './SkillPicker.vue'

const props = defineProps({
  jobId: { type: Number, required: true },
  initialJdText: { type: String, default: '' },
})
const emit = defineEmits(['status-change', 'extract-background'])

const jdText = ref(props.initialJdText || '')
const status = ref('none')
const model = ref(null)
const fallbackMode = ref(false)
const saving = ref(false)
const editMode = ref(false)
const showJd = ref(false)
const activeCards = ref(['hard', 'exp'])
const flatForm = ref({ education_min: '本科', work_years_min: 0, work_years_max: 99, required_skills: '' })
const newBonus = ref('')
const newExcl = ref('')

function statusText(s) {
  return { none: '未生成', draft: '待 HR 审核', approved: '已发布', rejected: '已驳回' }[s] || s
}

function _isValidModel(m) {
  // 必须是非空 dict + 有 hard_skills 数组（避免 view 模式崩在 model.hard_skills.length）
  return m && typeof m === 'object' && Array.isArray(m.hard_skills)
}

async function loadCompetency() {
  try {
    const resp = await competencyApi.get(props.jobId)
    const m = resp.competency_model
    model.value = _isValidModel(m) ? m : null
    // 若 model 残缺，无论 status 是什么都展示为 none，避免 ✓ 标签 + 空模型的矛盾
    status.value = model.value ? (resp.status || 'none') : 'none'
    emit('status-change', status.value)
  } catch {
    ElMessage.error('加载能力模型失败，请刷新页面重试')
  }
}

function onExtract() {
  if (!jdText.value.trim()) { ElMessage.warning('请先填 JD 原文'); return }
  showJd.value = false
  emit('extract-background', { jobId: props.jobId, jdText: jdText.value })
}

function onSkillSelect(row, skill) {
  row.name = skill.canonical_name
  if (skill.id) row.canonical_id = skill.id
}

function addBonus() {
  if (newBonus.value.trim()) { model.value.bonus_items.push(newBonus.value.trim()); newBonus.value = '' }
}
function addExcl() {
  if (newExcl.value.trim()) { model.value.exclusions.push(newExcl.value.trim()); newExcl.value = '' }
}

async function saveDraft() {
  saving.value = true
  try {
    await competencyApi.saveDraft(props.jobId, model.value)
    await loadCompetency()
    ElMessage.success('已保存草稿')
  } catch (e) {
    ElMessage.error('保存失败：' + (e.response?.data?.detail || e.message || '请重试'))
  } finally { saving.value = false }
}

async function submitApprove() {
  saving.value = true
  try {
    await competencyApi.approve(props.jobId, model.value)
    await loadCompetency()
    editMode.value = false
    ElMessage.success('已发布')
  } catch (e) {
    ElMessage.error('发布失败：' + (e.response?.data?.detail || e.message || '请重试'))
  } finally { saving.value = false }
}

async function submitFlat() {
  try {
    await competencyApi.manual(props.jobId, flatForm.value)
    fallbackMode.value = false
    await loadCompetency()
    ElMessage.success('已保存并发布')
  } catch (e) { ElMessage.error('保存失败: ' + (e.message || e)) }
}

onMounted(loadCompetency)
watch(() => props.jobId, loadCompetency)
watch(() => props.initialJdText, (val) => { if (val && !jdText.value) jdText.value = val })
</script>

<style scoped>
.ce { font-size: 13px; }

/* 顶部操作栏 */
.ce-topbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 0 12px; border-bottom: 1px solid #f0f0f0; margin-bottom: 14px;
}
.ce-topbar-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.ce-status-badge {
  display: inline-flex; align-items: center; gap: 6px;
  font-weight: 600; font-size: 13px;
}
.ce-status-badge .dot {
  width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
}
.ce-status-badge.none  .dot { background: #909399; }
.ce-status-badge.none  { color: #909399; }
.ce-status-badge.draft .dot { background: #e6a23c; }
.ce-status-badge.draft { color: #e6a23c; }
.ce-status-badge.approved .dot { background: #67c23a; }
.ce-status-badge.approved { color: #67c23a; }
.ce-status-badge.rejected .dot { background: #f56c6c; }
.ce-status-badge.rejected { color: #f56c6c; }

/* JD 输入区 */
.ce-jd-box { background: #f8f9fa; border-radius: 8px; padding: 12px; margin-bottom: 14px; }
.ce-jd-footer { margin-top: 10px; display: flex; gap: 8px; }
.slide-enter-active, .slide-leave-active { transition: all .2s ease; overflow: hidden; }
.slide-enter-from, .slide-leave-to { max-height: 0; opacity: 0; }
.slide-enter-to, .slide-leave-from { max-height: 400px; opacity: 1; }

/* 空状态 */
.ce-empty { text-align: center; padding: 40px 0; color: #909399; }
.ce-empty-icon { font-size: 40px; margin-bottom: 10px; }
.ce-empty p { margin-bottom: 14px; }

/* 概要数字 */
.ce-stats {
  display: flex; gap: 0; border: 1px solid #ebeef5; border-radius: 8px;
  overflow: hidden; margin-bottom: 16px;
}
.ce-stat-item {
  flex: 1; text-align: center; padding: 10px 4px;
  border-right: 1px solid #ebeef5;
}
.ce-stat-item:last-child { border-right: none; }
.ce-stat-n { display: block; font-size: 18px; font-weight: 700; color: #303133; }
.ce-stat-l { display: block; font-size: 11px; color: #909399; margin-top: 2px; }

/* 通用分区 */
.ce-section { margin-bottom: 16px; }
.ce-section-hd {
  font-size: 12px; font-weight: 600; color: #909399;
  text-transform: uppercase; letter-spacing: .5px;
  margin-bottom: 10px;
}
.ce-two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }

/* 硬技能卡片 */
.ce-skill-grid {
  display: flex; flex-wrap: wrap; gap: 8px;
}
.ce-skill-card {
  display: inline-flex; flex-direction: column; align-items: flex-start;
  padding: 6px 10px; border-radius: 6px; border: 1px solid #e4e7ed;
  background: #fff; min-width: 90px;
}
.ce-skill-card.level-精通 { border-color: #b7eb8f; background: #f6ffed; }
.ce-skill-card.level-熟练 { border-color: #91caff; background: #e6f4ff; }
.ce-skill-card.level-了解 { border-color: #d9d9d9; background: #fafafa; }
.ce-skill-name { font-size: 13px; font-weight: 500; color: #303133; }
.ce-skill-meta { display: flex; gap: 4px; margin-top: 4px; }
.ce-level-tag {
  font-size: 10px; padding: 1px 5px; border-radius: 3px;
}
.ce-skill-card.level-精通 .ce-level-tag { background: #b7eb8f; color: #135200; }
.ce-skill-card.level-熟练 .ce-level-tag { background: #91caff; color: #003eb3; }
.ce-skill-card.level-了解 .ce-level-tag { background: #e8e8e8; color: #595959; }
.ce-must-tag {
  font-size: 10px; padding: 1px 5px; border-radius: 3px;
  background: #fff1f0; color: #cf1322;
}

/* 软技能 */
.ce-tag-row { display: flex; flex-wrap: wrap; gap: 6px; }
.ce-soft-tag { display: inline-flex; align-items: center; gap: 4px; }
.ce-soft-stage { font-size: 10px; color: #909399; }

/* 信息块 */
.ce-info-block { }
.ce-info-row {
  display: flex; gap: 8px; margin-bottom: 5px; font-size: 13px;
}
.ce-info-row .lbl { color: #909399; min-width: 32px; }

/* 考察维度 */
.ce-dimension-list { display: flex; flex-direction: column; gap: 8px; }
.ce-dimension-item {
  background: #fafafa; border-radius: 6px; padding: 10px 12px;
  border-left: 3px solid #1677ff;
}
.ce-dim-header { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.ce-dim-index {
  width: 20px; height: 20px; border-radius: 50%; background: #1677ff;
  color: #fff; font-size: 11px; display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.ce-dim-name { font-weight: 500; }
.ce-dim-desc { font-size: 12px; color: #606266; }

/* 编辑模式折叠 */
.ce-edit-collapse { margin-top: 4px; }
.ce-add-btn { margin-top: 8px; }
.ce-soft-edit { display: flex; flex-direction: column; gap: 8px; }
.ce-soft-row { display: flex; gap: 8px; align-items: center; }
.ce-tag-edit-row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.ce-tag-edit-row .lbl2 { font-weight: 500; color: #606266; min-width: 44px; }
</style>
