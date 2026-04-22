<template>
  <div class="intake-page">
    <!-- 顶部控制栏 -->
    <el-card class="control-bar" shadow="never">
      <div class="control-row">
        <div class="status-block">
          <el-tag :type="status?.running ? 'success' : 'info'" effect="dark">
            调度器: {{ status?.running ? '运行中' : '已暂停' }}
          </el-tag>
          <span class="stat">
            今日操作: {{ status?.daily_cap_used ?? 0 }} / {{ status?.daily_cap_max ?? 0 }}
          </span>
          <span class="stat">
            上轮处理: {{ status?.last_batch_size ?? 0 }}
          </span>
          <span class="stat" v-if="status?.next_run_at">
            下次: {{ formatTime(status.next_run_at) }}
          </span>
        </div>
        <div class="actions">
          <el-button
            v-if="status?.running"
            type="warning"
            size="small"
            @click="doPause"
          >暂停调度</el-button>
          <el-button
            v-else
            type="success"
            size="small"
            @click="doResume"
          >恢复调度</el-button>
          <el-button
            type="primary"
            size="small"
            :loading="ticking"
            @click="doTickNow"
          >立即扫一次</el-button>
          <el-button size="small" @click="loadStatus">刷新状态</el-button>
        </div>
      </div>
    </el-card>

    <!-- 候选人列表 -->
    <el-card style="margin-top: 16px;" shadow="never">
      <div class="filter-bar">
        <el-select
          v-model="statusFilter"
          placeholder="全部状态"
          clearable
          style="width: 180px"
          @change="reload"
        >
          <el-option label="收集中" value="collecting" />
          <el-option label="等待回复" value="awaiting_reply" />
          <el-option label="待人工" value="pending_human" />
          <el-option label="已完成" value="complete" />
          <el-option label="已放弃" value="abandoned" />
        </el-select>
        <el-input
          v-model="search"
          placeholder="按姓名/Boss ID 搜索"
          clearable
          style="width: 240px; margin-left: 12px"
          @clear="reload"
          @keyup.enter="reload"
        />
        <el-button type="primary" size="default" style="margin-left: 12px" @click="reload">
          搜索
        </el-button>
      </div>

      <el-table
        :data="filteredItems"
        v-loading="loading"
        border
        row-key="resume_id"
        @expand-change="handleExpandChange"
      >
        <el-table-column type="expand">
          <template #default="{ row }">
            <SlotsPanel :resume-id="row.resume_id" />
          </template>
        </el-table-column>
        <el-table-column prop="name" label="姓名" min-width="120" />
        <el-table-column prop="boss_id" label="Boss ID" min-width="160" />
        <el-table-column prop="job_title" label="目标岗位" min-width="160">
          <template #default="{ row }">
            <span v-if="row.job_title">{{ row.job_title }}</span>
            <span v-else style="color: #c0c4cc">未匹配</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.intake_status)">
              {{ statusText(row.intake_status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="进度" width="160">
          <template #default="{ row }">
            <el-progress
              :percentage="progressPct(row)"
              :stroke-width="10"
              :format="() => `${row.progress_done}/${row.progress_total}`"
            />
          </template>
        </el-table-column>
        <el-table-column label="最近活动" width="170">
          <template #default="{ row }">
            {{ row.last_activity_at ? formatTime(row.last_activity_at) : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.intake_status !== 'complete' && row.intake_status !== 'abandoned'"
              size="small"
              type="success"
              link
              @click="doForceComplete(row)"
            >标记完成</el-button>
            <el-button
              v-if="row.intake_status !== 'abandoned'"
              size="small"
              type="danger"
              link
              @click="doAbandon(row)"
            >放弃</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        style="margin-top: 16px; justify-content: flex-end; display: flex"
        v-model:current-page="page"
        v-model:page-size="size"
        :total="total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        @current-change="loadCandidates"
        @size-change="loadCandidates"
      />
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import SlotsPanel from './SlotsPanel.vue'
import {
  listIntakeCandidates,
  abandonCandidate,
  forceComplete,
  getSchedulerStatus,
  pauseScheduler,
  resumeScheduler,
  tickNow,
} from '../api/intake'

const status = ref(null)
const ticking = ref(false)

const loading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const statusFilter = ref('')
const search = ref('')

let statusTimer = null

const filteredItems = computed(() => {
  const kw = (search.value || '').trim().toLowerCase()
  if (!kw) return items.value
  return items.value.filter(
    (it) =>
      (it.name || '').toLowerCase().includes(kw) ||
      (it.boss_id || '').toLowerCase().includes(kw)
  )
})

function progressPct(row) {
  if (!row.progress_total) return 0
  return Math.round((row.progress_done / row.progress_total) * 100)
}

function statusTagType(s) {
  return {
    collecting: 'primary',
    awaiting_reply: 'warning',
    pending_human: 'danger',
    complete: 'success',
    abandoned: 'info',
  }[s] || ''
}

function statusText(s) {
  return {
    collecting: '收集中',
    awaiting_reply: '等待回复',
    pending_human: '待人工',
    complete: '已完成',
    abandoned: '已放弃',
  }[s] || s
}

function formatTime(t) {
  if (!t) return ''
  try {
    const d = new Date(t)
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch {
    return t
  }
}

async function loadStatus() {
  try {
    status.value = await getSchedulerStatus()
  } catch (e) {
    // silent — status panel will just stay stale
  }
}

async function loadCandidates() {
  loading.value = true
  try {
    const params = { page: page.value, size: size.value }
    if (statusFilter.value) params.status = statusFilter.value
    const res = await listIntakeCandidates(params)
    items.value = res.items || []
    total.value = res.total || 0
  } catch (e) {
    ElMessage.error('加载候选人列表失败')
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  loadCandidates()
}

function handleExpandChange() {
  // SlotsPanel mounts on expand and self-loads; nothing to do here.
}

async function doPause() {
  try {
    await pauseScheduler()
    ElMessage.success('已暂停')
    loadStatus()
  } catch (e) {
    ElMessage.error('暂停失败')
  }
}

async function doResume() {
  try {
    await resumeScheduler()
    ElMessage.success('已恢复')
    loadStatus()
  } catch (e) {
    ElMessage.error('恢复失败')
  }
}

async function doTickNow() {
  ticking.value = true
  try {
    await tickNow()
    ElMessage.success('已触发一次扫描')
    loadStatus()
    loadCandidates()
  } catch (e) {
    ElMessage.error('触发失败')
  } finally {
    ticking.value = false
  }
}

async function doAbandon(row) {
  try {
    await ElMessageBox.confirm(`确定放弃候选人 ${row.name} 吗？`, '提示', { type: 'warning' })
  } catch {
    return
  }
  try {
    await abandonCandidate(row.resume_id)
    ElMessage.success('已放弃')
    loadCandidates()
  } catch (e) {
    ElMessage.error('操作失败')
  }
}

async function doForceComplete(row) {
  try {
    await ElMessageBox.confirm(`确定标记 ${row.name} 为已完成吗？`, '提示', { type: 'warning' })
  } catch {
    return
  }
  try {
    await forceComplete(row.resume_id)
    ElMessage.success('已标记完成')
    loadCandidates()
  } catch (e) {
    ElMessage.error('操作失败')
  }
}

onMounted(() => {
  loadStatus()
  loadCandidates()
  statusTimer = setInterval(loadStatus, 30000)
})

onUnmounted(() => {
  if (statusTimer) clearInterval(statusTimer)
})
</script>

<style scoped>
.intake-page {
  padding: 0;
}
.control-bar :deep(.el-card__body) {
  padding: 14px 20px;
}
.control-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}
.status-block {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}
.stat {
  font-size: 13px;
  color: #606266;
}
.actions {
  display: flex;
  gap: 8px;
}
.filter-bar {
  display: flex;
  align-items: center;
  margin-bottom: 16px;
}
</style>
