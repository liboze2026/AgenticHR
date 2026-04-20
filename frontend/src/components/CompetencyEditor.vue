<template>
  <div class="competency-editor">
    <!-- 状态指示 + JD 原文 -->
    <el-card class="header-card" shadow="never">
      <div class="status-row">
        <span class="label">状态:</span>
        <el-tag :type="statusTag(status)" size="large">{{ statusText(status) }}</el-tag>
        <el-button
          v-if="status === 'none' || status === 'rejected'"
          type="primary" @click="onExtract" :loading="extracting"
          :disabled="!jdText.trim()">
          从 JD 抽取
        </el-button>
        <el-button
          v-if="status === 'approved'"
          type="warning" @click="onExtract" :loading="extracting">
          重新抽取
        </el-button>
      </div>
      <el-input
        v-model="jdText" type="textarea" :rows="6"
        placeholder="粘贴 JD 原文..." class="jd-input"
      />
    </el-card>

    <!-- 手填降级模式 -->
    <el-alert
      v-if="fallbackMode" type="warning" :closable="false"
      title="LLM 抽取失败, 请手工填写" show-icon class="fallback-alert"
    />
    <el-form v-if="fallbackMode" :model="flatForm" label-width="100px" class="fallback-form">
      <el-form-item label="学历要求">
        <el-select v-model="flatForm.education_min">
          <el-option label="大专" value="大专" />
          <el-option label="本科" value="本科" />
          <el-option label="硕士" value="硕士" />
          <el-option label="博士" value="博士" />
        </el-select>
      </el-form-item>
      <el-form-item label="工作年限">
        <el-input-number v-model="flatForm.work_years_min" :min="0" :max="30" /> ~
        <el-input-number v-model="flatForm.work_years_max" :min="0" :max="30" />
      </el-form-item>
      <el-form-item label="必备技能 (逗号分隔)">
        <el-input v-model="flatForm.required_skills" placeholder="Python,FastAPI,..." />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="submitFlat">保存并发布</el-button>
        <el-button @click="fallbackMode=false">取消</el-button>
      </el-form-item>
    </el-form>

    <!-- 6 折叠卡片 -->
    <el-collapse v-if="!fallbackMode && model" v-model="activeCards" class="cards">
      <el-collapse-item title="硬技能" name="hard">
        <el-table :data="model.hard_skills" border size="small">
          <el-table-column label="技能" min-width="200">
            <template #default="{ row }">
              <SkillPicker v-model="row.name" @select="onSkillSelect(row, $event)" />
            </template>
          </el-table-column>
          <el-table-column label="等级" width="120">
            <template #default="{ row }">
              <el-select v-model="row.level" size="small">
                <el-option label="了解" value="了解" />
                <el-option label="熟练" value="熟练" />
                <el-option label="精通" value="精通" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="权重" width="160">
            <template #default="{ row }">
              <el-slider v-model="row.weight" :min="1" :max="10" show-input />
            </template>
          </el-table-column>
          <el-table-column label="必须" width="80" align="center">
            <template #default="{ row }">
              <el-checkbox v-model="row.must_have" />
            </template>
          </el-table-column>
          <el-table-column label="" width="60">
            <template #default="{ $index }">
              <el-button size="small" type="danger" link @click="removeHard($index)">删</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-button size="small" @click="addHard" class="add-btn">+ 添加技能</el-button>
      </el-collapse-item>

      <el-collapse-item title="软技能" name="soft">
        <el-table :data="model.soft_skills" border size="small">
          <el-table-column label="技能" min-width="200">
            <template #default="{ row }">
              <el-input v-model="row.name" size="small" />
            </template>
          </el-table-column>
          <el-table-column label="权重" width="160">
            <template #default="{ row }">
              <el-slider v-model="row.weight" :min="1" :max="10" show-input />
            </template>
          </el-table-column>
          <el-table-column label="评估阶段" width="130">
            <template #default="{ row }">
              <el-select v-model="row.assessment_stage" size="small">
                <el-option label="简历" value="简历" />
                <el-option label="IM" value="IM" />
                <el-option label="面试" value="面试" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="" width="60">
            <template #default="{ $index }">
              <el-button size="small" type="danger" link @click="removeSoft($index)">删</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-button size="small" @click="addSoft" class="add-btn">+ 添加软技能</el-button>
      </el-collapse-item>

      <el-collapse-item title="工作经验" name="exp">
        <el-form :model="model.experience" label-width="120px" size="small">
          <el-form-item label="最少年限">
            <el-input-number v-model="model.experience.years_min" :min="0" :max="30" />
          </el-form-item>
          <el-form-item label="最高年限">
            <el-input-number v-model="model.experience.years_max" :min="0" :max="30" />
            <el-checkbox :model-value="model.experience.years_max === null"
                          @update:model-value="v => model.experience.years_max = v ? null : 99"
                          style="margin-left:10px">
              不限
            </el-checkbox>
          </el-form-item>
          <el-form-item label="行业">
            <el-tag v-for="(ind, idx) in model.experience.industries" :key="idx"
                     closable @close="model.experience.industries.splice(idx,1)">
              {{ ind }}
            </el-tag>
            <el-input size="small" v-model="newIndustry" @keyup.enter="addIndustry" style="width:120px" />
            <el-button size="small" @click="addIndustry">+</el-button>
          </el-form-item>
          <el-form-item label="公司规模">
            <el-select v-model="model.experience.company_scale" clearable>
              <el-option label="大厂" value="大厂" />
              <el-option label="独角兽" value="独角兽" />
              <el-option label="中型" value="中型" />
              <el-option label="初创" value="初创" />
            </el-select>
          </el-form-item>
        </el-form>
      </el-collapse-item>

      <el-collapse-item title="学历" name="edu">
        <el-form :model="model.education" label-width="120px" size="small">
          <el-form-item label="最低学历">
            <el-radio-group v-model="model.education.min_level">
              <el-radio-button label="大专" />
              <el-radio-button label="本科" />
              <el-radio-button label="硕士" />
              <el-radio-button label="博士" />
            </el-radio-group>
          </el-form-item>
          <el-form-item label="名校加分">
            <el-switch v-model="model.education.prestigious_bonus" />
          </el-form-item>
        </el-form>
      </el-collapse-item>

      <el-collapse-item title="加分项 / 淘汰项" name="bonus">
        <div class="tag-row">
          <span class="label">加分项:</span>
          <el-tag v-for="(b, idx) in model.bonus_items" :key="idx"
                   closable @close="model.bonus_items.splice(idx,1)" type="success">
            {{ b }}
          </el-tag>
          <el-input size="small" v-model="newBonus" @keyup.enter="addBonus" style="width:160px" />
          <el-button size="small" @click="addBonus">+</el-button>
        </div>
        <div class="tag-row">
          <span class="label">淘汰项:</span>
          <el-tag v-for="(e, idx) in model.exclusions" :key="idx"
                   closable @close="model.exclusions.splice(idx,1)" type="danger">
            {{ e }}
          </el-tag>
          <el-input size="small" v-model="newExcl" @keyup.enter="addExcl" style="width:160px" />
          <el-button size="small" @click="addExcl">+</el-button>
        </div>
      </el-collapse-item>

      <el-collapse-item title="考察维度" name="assess">
        <el-table :data="model.assessment_dimensions" border size="small">
          <el-table-column label="维度" min-width="140">
            <template #default="{ row }">
              <el-input v-model="row.name" size="small" />
            </template>
          </el-table-column>
          <el-table-column label="描述" min-width="200">
            <template #default="{ row }">
              <el-input v-model="row.description" size="small" />
            </template>
          </el-table-column>
          <el-table-column label="题型" min-width="200">
            <template #default="{ row }">
              <el-tag v-for="(q, qi) in row.question_types" :key="qi" closable
                       @close="row.question_types.splice(qi,1)" style="margin-right:4px">
                {{ q }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="" width="60">
            <template #default="{ $index }">
              <el-button size="small" type="danger" link @click="removeAssess($index)">删</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-button size="small" @click="addAssess" class="add-btn">+ 添加维度</el-button>
      </el-collapse-item>
    </el-collapse>

    <!-- 底部按钮 -->
    <div v-if="!fallbackMode && model" class="footer">
      <el-button @click="saveDraft" :loading="saving">保存草稿</el-button>
      <el-button type="primary" @click="submitApprove" :loading="saving">通过并发布</el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { competencyApi, hitlApi } from '../api'
import SkillPicker from './SkillPicker.vue'

const props = defineProps({ jobId: { type: Number, required: true } })
const emit = defineEmits(['status-change'])

const jdText = ref('')
const status = ref('none')
const model = ref(null)
const fallbackMode = ref(false)
const extracting = ref(false)
const saving = ref(false)
const activeCards = ref(['hard', 'exp', 'edu'])
const pendingTaskId = ref(null)
const flatForm = ref({ education_min: '本科', work_years_min: 0, work_years_max: 99, required_skills: '' })
const newIndustry = ref('')
const newBonus = ref('')
const newExcl = ref('')

function statusText(s) {
  return { none: '未生成', draft: '待审', approved: '已发布', rejected: '已驳回' }[s] || s
}
function statusTag(s) {
  return { none: 'info', draft: 'warning', approved: 'success', rejected: 'danger' }[s] || ''
}

async function loadCompetency() {
  try {
    const resp = await competencyApi.get(props.jobId)
    model.value = resp.competency_model || null
    status.value = resp.status || 'none'
    emit('status-change', status.value)
  } catch (e) {
    console.error(e)
  }
}

async function onExtract() {
  if (!jdText.value.trim()) {
    ElMessage.warning('请先填 JD 原文')
    return
  }
  extracting.value = true
  try {
    const resp = await competencyApi.extract(props.jobId)
    if (resp.status === 'failed') {
      fallbackMode.value = true
      ElMessage.warning('LLM 抽取失败, 进入手工填写模式')
    } else {
      pendingTaskId.value = resp.hitl_task_id
      await loadCompetency()
      ElMessage.success('抽取完成, 请审核')
    }
  } catch (e) {
    ElMessage.error('抽取失败: ' + (e.message || e))
  } finally {
    extracting.value = false
  }
}

function addHard() {
  model.value.hard_skills.push({ name: '', level: '熟练', weight: 5, must_have: false })
}
function removeHard(i) { model.value.hard_skills.splice(i, 1) }
function addSoft() {
  model.value.soft_skills.push({ name: '', weight: 5, assessment_stage: '面试' })
}
function removeSoft(i) { model.value.soft_skills.splice(i, 1) }
function addAssess() {
  model.value.assessment_dimensions.push({ name: '', description: '', question_types: [] })
}
function removeAssess(i) { model.value.assessment_dimensions.splice(i, 1) }
function addIndustry() {
  if (newIndustry.value.trim()) {
    model.value.experience.industries.push(newIndustry.value.trim())
    newIndustry.value = ''
  }
}
function addBonus() {
  if (newBonus.value.trim()) { model.value.bonus_items.push(newBonus.value.trim()); newBonus.value = '' }
}
function addExcl() {
  if (newExcl.value.trim()) { model.value.exclusions.push(newExcl.value.trim()); newExcl.value = '' }
}

function onSkillSelect(row, skill) {
  row.name = skill.canonical_name
  if (skill.id) row.canonical_id = skill.id
}

async function saveDraft() {
  if (!pendingTaskId.value) {
    ElMessage.warning('没有待审任务, 无法保存草稿. 请先点"从 JD 抽取"')
    return
  }
  saving.value = true
  try {
    await hitlApi.edit(pendingTaskId.value, model.value, 'draft save')
    await loadCompetency()
    ElMessage.success('已保存')
  } finally { saving.value = false }
}

async function submitApprove() {
  saving.value = true
  try {
    if (pendingTaskId.value) {
      await hitlApi.edit(pendingTaskId.value, model.value, 'approved via editor')
    }
    await loadCompetency()
    ElMessage.success('已发布')
  } catch (e) {
    ElMessage.error('发布失败: ' + (e.message || e))
  } finally { saving.value = false }
}

async function submitFlat() {
  try {
    await competencyApi.manual(props.jobId, flatForm.value)
    fallbackMode.value = false
    await loadCompetency()
    ElMessage.success('已保存并发布')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.message || e))
  }
}

onMounted(loadCompetency)
watch(() => props.jobId, loadCompetency)
</script>

<style scoped>
.competency-editor { padding: 8px 0; }
.header-card { margin-bottom: 12px; }
.status-row { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.status-row .label { font-weight: 500; color: #606266; }
.jd-input { font-family: monospace; }
.cards { margin-top: 8px; }
.add-btn { margin-top: 8px; }
.tag-row { margin-bottom: 10px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.tag-row .label { font-weight: 500; margin-right: 8px; width: 70px; }
.footer { margin-top: 16px; text-align: right; }
.fallback-alert { margin: 10px 0; }
.fallback-form { background: #fafafa; padding: 16px; border-radius: 4px; }
</style>
