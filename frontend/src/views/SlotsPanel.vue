<template>
  <div class="slots-panel" v-loading="loading">
    <div v-if="detail">
      <!-- 硬性槽位 -->
      <el-divider content-position="left">硬性信息</el-divider>
      <el-table :data="hardSlots" size="small" border>
        <el-table-column prop="slot_key" label="字段" width="180" />
        <el-table-column label="值">
          <template #default="{ row }">
            <span v-if="row.value && editingId !== row.id">{{ row.value }}</span>
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
        <el-table-column label="询问次数" width="100">
          <template #default="{ row }">{{ row.ask_count }}</template>
        </el-table-column>
        <el-table-column label="来源" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.source" size="small">{{ row.source }}</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button
              v-if="!row.value"
              size="small"
              type="primary"
              link
              @click="startEdit(row)"
            >填写</el-button>
            <el-button
              v-else
              size="small"
              link
              @click="startEdit(row)"
            >修改</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- PDF 槽位 -->
      <el-divider content-position="left">PDF 简历</el-divider>
      <div v-if="pdfSlot">
        <el-tag v-if="pdfSlot.value" type="success">已收到 ({{ pdfSlot.source || 'unknown' }})</el-tag>
        <el-tag v-else type="info">未收到</el-tag>
        <span v-if="pdfSlot.ask_count > 0" style="margin-left: 12px; color: #909399; font-size: 12px;">
          已询问 {{ pdfSlot.ask_count }} 次
        </span>
      </div>
      <div v-else style="color: #909399; font-size: 13px;">暂无 PDF 槽位</div>

      <!-- 软性问答 -->
      <el-divider content-position="left">软性问答</el-divider>
      <el-table v-if="softSlots.length" :data="softSlots" size="small" border>
        <el-table-column label="问题" min-width="240">
          <template #default="{ row }">
            {{ row.question_meta?.question || row.last_ask_text || row.slot_key }}
          </template>
        </el-table-column>
        <el-table-column label="回答" min-width="240">
          <template #default="{ row }">
            <span v-if="row.value">{{ row.value }}</span>
            <el-tag v-else type="info" size="small">待回答</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="询问次数" width="100">
          <template #default="{ row }">{{ row.ask_count }}</template>
        </el-table-column>
      </el-table>
      <div v-else style="color: #909399; font-size: 13px;">暂无软性问题</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { getIntakeCandidate, patchIntakeSlot } from '../api/intake'

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
  if (!val) {
    editingId.value = null
    return
  }
  if (val === row.value) {
    editingId.value = null
    return
  }
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
</style>
