<template>
  <div class="slots-panel" v-loading="loading">
    <div v-if="detail">
      <!-- 硬性槽位 -->
      <el-divider content-position="left">硬性信息</el-divider>
      <el-table :data="hardSlots" size="small" border>
        <el-table-column label="字段" width="110">
          <template #default="{ row }">
            <span class="slot-label">{{ SLOT_LABELS[row.slot_key] || row.slot_key }}</span>
          </template>
        </el-table-column>
        <el-table-column label="候选人原话" min-width="260">
          <template #default="{ row }">
            <template v-if="row.value && editingId !== row.id">
              <span v-if="row.phrase_timestamps?.length" class="phrase-block">
                <template v-for="(p, i) in row.phrase_timestamps" :key="i">
                  <span v-if="i > 0" class="phrase-sep"> | </span>
                  <span class="phrase-text">{{ p.text }}</span>
                  <span v-if="p.sent_at" class="phrase-time">（{{ formatShortTime(p.sent_at) }}）</span>
                </template>
              </span>
              <span v-else class="slot-value">{{ row.value }}</span>
            </template>
            <el-input
              v-else
              v-model="editValues[row.id]"
              size="small"
              :placeholder="row.last_ask_text || '请输入'"
              @blur="saveSlot(row)"
              @keyup.enter="saveSlot(row)"
            />
          </template>
        </el-table-column>
        <el-table-column label="来源" width="120">
          <template #default="{ row }">
            <div class="meta-cell">
              <el-tag v-if="row.source" size="small" :type="row.source === 'llm' ? 'success' : 'info'">
                {{ SOURCE_LABELS[row.source] || row.source }}
              </el-tag>
              <span v-if="row.ask_count > 0" class="ask-count">问{{ row.ask_count }}次</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="72">
          <template #default="{ row }">
            <el-button v-if="!row.value" size="small" type="primary" link @click="startEdit(row)">填写</el-button>
            <el-button v-else size="small" link @click="startEdit(row)">修改</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- PDF 槽位 -->
      <el-divider content-position="left">PDF 简历</el-divider>
      <div v-if="pdfSlot" class="pdf-row">
        <el-tag v-if="pdfSlot.value" type="success">已收到 ({{ SOURCE_LABELS[pdfSlot.source] || pdfSlot.source || 'unknown' }})</el-tag>
        <el-tag v-else type="info">未收到</el-tag>
        <span v-if="pdfSlot.ask_count > 0" class="ask-count-inline">已询问 {{ pdfSlot.ask_count }} 次</span>
        <span v-if="pdfSlot.msg_sent_at" class="phrase-time" style="margin-left: 8px">（{{ formatShortTime(pdfSlot.msg_sent_at) }}）</span>
      </div>
      <div v-else class="empty-text">暂无 PDF 槽位</div>

      <!-- 软性问答 -->
      <el-divider content-position="left">软性问答</el-divider>
      <el-table v-if="softSlots.length" :data="softSlots" size="small" border>
        <el-table-column label="问题" min-width="180">
          <template #default="{ row }">
            {{ row.question_meta?.question || row.last_ask_text || row.slot_key }}
          </template>
        </el-table-column>
        <el-table-column label="候选人回答" min-width="260">
          <template #default="{ row }">
            <template v-if="row.value">
              <span v-if="row.phrase_timestamps?.length" class="phrase-block">
                <template v-for="(p, i) in row.phrase_timestamps" :key="i">
                  <span v-if="i > 0" class="phrase-sep"> | </span>
                  <span class="phrase-text">{{ p.text }}</span>
                  <span v-if="p.sent_at" class="phrase-time">（{{ formatShortTime(p.sent_at) }}）</span>
                </template>
              </span>
              <span v-else class="slot-value">{{ row.value }}</span>
            </template>
            <el-tag v-else type="info" size="small">待回答</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="100">
          <template #default="{ row }">
            <div class="meta-cell">
              <el-tag v-if="row.source" size="small" :type="row.source === 'llm' ? 'success' : 'info'">
                {{ SOURCE_LABELS[row.source] || row.source }}
              </el-tag>
              <span v-if="row.ask_count > 0" class="ask-count">问{{ row.ask_count }}次</span>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <div v-else class="empty-text">暂无软性问题</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { getIntakeCandidate, patchIntakeSlot } from '../api/intake'

const SLOT_LABELS = {
  arrival_date: '到岗时间',
  free_slots: '空闲时间',
  intern_duration: '实习时长',
  pdf: 'PDF简历',
}

const SOURCE_LABELS = {
  llm: 'AI提取',
  manual: '手动填写',
  plugin_detected: '插件检测',
}

const props = defineProps({
  resumeId: { type: [Number, String], required: true },
})

const loading = ref(false)
const detail = ref(null)
const editingId = ref(null)
const editValues = reactive({})

const hardSlots = computed(() =>
  (detail.value?.slots || []).filter((s) => s.slot_category === 'hard')
)
const pdfSlot = computed(() =>
  (detail.value?.slots || []).find((s) => s.slot_category === 'pdf')
)
const softSlots = computed(() =>
  (detail.value?.slots || []).filter((s) => s.slot_category === 'soft')
)

function formatShortTime(t) {
  if (!t) return ''
  try {
    const d = new Date(t)
    const now = new Date()
    const sameDay =
      d.getFullYear() === now.getFullYear() &&
      d.getMonth() === now.getMonth() &&
      d.getDate() === now.getDate()
    if (sameDay) {
      return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
    }
    return d.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
  } catch {
    return String(t)
  }
}

async function load() {
  if (!props.resumeId) return
  loading.value = true
  try {
    detail.value = await getIntakeCandidate(props.resumeId)
  } catch (e) {
    ElMessage.error('加载候选人详情失败')
  } finally {
    loading.value = false
  }
}

function startEdit(row) {
  editingId.value = row.id
  editValues[row.id] = row.value || ''
}

async function saveSlot(row) {
  const val = (editValues[row.id] || '').trim()
  if (!val) { editingId.value = null; return }
  if (val === row.value) { editingId.value = null; return }
  try {
    const updated = await patchIntakeSlot(row.id, val)
    Object.assign(row, updated)
    ElMessage.success('已保存')
    editingId.value = null
  } catch (e) {
    ElMessage.error('保存失败')
  }
}

watch(() => props.resumeId, load)
onMounted(load)

defineExpose({ reload: load })
</script>

<style scoped>
.slots-panel {
  padding: 12px 24px;
  background: #fafafa;
}
.slot-label {
  font-weight: 500;
  color: #303133;
}
.slot-value {
  color: #303133;
  line-height: 1.5;
}
.phrase-block {
  line-height: 1.6;
}
.phrase-text {
  color: #303133;
}
.phrase-sep {
  color: #909399;
  margin: 0 2px;
}
.phrase-time {
  font-size: 11px;
  color: #909399;
}
.empty-text {
  font-size: 13px;
  color: #909399;
}
.meta-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.ask-count {
  font-size: 11px;
  color: #909399;
}
.pdf-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 4px 0;
}
.ask-count-inline {
  font-size: 12px;
  color: #909399;
}
</style>
