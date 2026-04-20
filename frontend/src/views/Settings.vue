<template>
  <div>
    <h2 style="margin-bottom: 24px">设置</h2>
    <el-tabs>
      <el-tab-pane label="AI 配置">
        <el-card>
          <el-alert type="warning" :closable="false" show-icon style="margin-bottom: 16px;">
            <template #default>
              配置文件位于程序目录下的 <b>.env</b> 文件中，修改后需<b>重启服务</b>才能生效。
            </template>
          </el-alert>
          <el-form label-width="120px">
            <el-form-item label="AI 状态">
              <el-tag :type="aiStatus.enabled ? 'success' : 'info'">{{ aiStatus.enabled ? '已启用' : '未启用' }}</el-tag>
              <el-tag :type="aiStatus.configured ? 'success' : 'warning'" style="margin-left: 8px">{{ aiStatus.configured ? '已配置' : '未配置' }}</el-tag>
            </el-form-item>
            <el-form-item label="模型">{{ aiStatus.model || '-' }}</el-form-item>
            <el-form-item>
              <el-button @click="testService('ai')">检测状态</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="候选人评分权重">
        <el-card>
          <div class="weights-intro">
            <p>设置候选人与岗位匹配时各维度的评分占比，总和必须为 <strong>100%</strong>。</p>
            <p style="color: #909399; font-size: 13px; margin-top: 4px;">这些权重将在简历匹配模块中用于计算候选人综合匹配分数。</p>
          </div>

          <div class="weight-dims">
            <div v-for="dim in dims" :key="dim.key" class="weight-row">
              <div class="weight-label">
                <span class="dim-name">{{ dim.label }}</span>
                <span class="dim-desc">{{ dim.desc }}</span>
              </div>
              <div class="weight-input">
                <el-input-number
                  v-model="weights[dim.key]"
                  :min="0" :max="100" :step="5"
                  controls-position="right"
                  style="width: 110px"
                  @change="onWeightChange"
                />
                <span class="pct">%</span>
              </div>
              <div class="weight-bar-wrap">
                <div class="weight-bar" :style="{ width: weights[dim.key] + '%', background: dim.color }"></div>
              </div>
            </div>
          </div>

          <div class="weight-total" :class="{ 'total-ok': total === 100, 'total-err': total !== 100 }">
            合计：{{ total }}%
            <span v-if="total !== 100" style="margin-left: 8px; font-size: 13px;">（需等于 100%）</span>
          </div>

          <div style="margin-top: 20px">
            <el-button type="primary" :disabled="total !== 100" :loading="saving" @click="saveWeights">
              保存权重配置
            </el-button>
            <el-button @click="resetWeights">恢复默认</el-button>
          </div>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="Boss 直聘">
        <el-card>
          <el-form label-width="120px">
            <el-form-item label="适配器状态">
              <el-tag :type="bossStatus.is_available ? 'success' : 'info'">{{ bossStatus.adapter_type }}</el-tag>
            </el-form-item>
            <el-form-item label="今日操作次数">{{ bossStatus.operations_today }} / {{ bossStatus.max_operations_today }}</el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <el-tab-pane label="飞书">
        <el-card>
          <el-form label-width="120px">
            <el-form-item label="连接状态">
              <el-tag :type="feishuStatus.configured ? 'success' : 'warning'">{{ feishuStatus.configured ? '已配置' : '未配置' }}</el-tag>
            </el-form-item>
            <el-form-item>
              <p style="color: #999; font-size: 13px">飞书、邮箱、腾讯会议的凭证请在 .env 文件中配置</p>
            </el-form-item>
            <el-form-item>
              <el-button @click="testService('feishu')">检测状态</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import api, { aiApi, bossApi, settingsApi } from '../api'

const aiStatus = ref({ enabled: false, configured: false, model: '' })
const bossStatus = ref({ adapter_type: '', is_available: false, operations_today: 0, max_operations_today: 0 })
const feishuStatus = ref({ configured: false })

const DEFAULTS = { skill_match: 35, experience: 30, seniority: 15, education: 10, industry: 10 }

const dims = [
  { key: 'skill_match', label: '技能匹配', desc: '候选人掌握的专业技能与岗位要求的吻合度', color: '#409eff' },
  { key: 'experience', label: '工作经验', desc: '相关工作年限与经验深度', color: '#67c23a' },
  { key: 'seniority',  label: '职位级别', desc: '候选人当前职级与目标岗位的对齐程度', color: '#e6a23c' },
  { key: 'education',  label: '教育背景', desc: '学历、专业与岗位要求的匹配', color: '#909399' },
  { key: 'industry',   label: '行业经验', desc: '候选人在同行业或相关行业的工作经验', color: '#f56c6c' },
]

const weights = ref({ ...DEFAULTS })
const saving = ref(false)

const total = computed(() => Object.values(weights.value).reduce((s, v) => s + (v || 0), 0))

function onWeightChange() { /* reactive via computed */ }

function resetWeights() {
  weights.value = { ...DEFAULTS }
}

async function saveWeights() {
  saving.value = true
  try {
    await settingsApi.saveScoringWeights(weights.value)
    ElMessage.success('评分权重已保存')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function loadStatus() {
  try { aiStatus.value = await aiApi.status() } catch {}
  try { bossStatus.value = await bossApi.status() } catch {}
  try { feishuStatus.value = await api.get('/feishu/status') } catch {}
}

async function loadWeights() {
  try {
    const data = await settingsApi.getScoringWeights()
    weights.value = data
  } catch {}
}

onMounted(() => { loadStatus(); loadWeights() })

const serviceLabels = { feishu: '飞书', ai: 'AI', email: '邮箱', meeting: '腾讯会议' }

const testService = async (serviceName) => {
  try {
    const res = await fetch('/api/health')
    const data = await res.json()
    const svc = data.services?.[serviceName]
    if (svc?.configured) {
      ElMessage.success(serviceLabels[serviceName] + ' 已配置')
    } else {
      ElMessage.warning(serviceLabels[serviceName] + ' 未配置，请在 .env 中设置')
    }
  } catch {
    ElMessage.error('无法连接服务器')
  }
}
</script>

<style scoped>
.weights-intro { margin-bottom: 24px; }
.weight-dims { display: flex; flex-direction: column; gap: 16px; }
.weight-row {
  display: grid;
  grid-template-columns: 200px 140px 1fr;
  align-items: center;
  gap: 16px;
}
.weight-label { display: flex; flex-direction: column; }
.dim-name { font-weight: 600; font-size: 14px; }
.dim-desc { font-size: 12px; color: #909399; margin-top: 2px; }
.weight-input { display: flex; align-items: center; gap: 6px; }
.pct { color: #606266; font-size: 14px; }
.weight-bar-wrap {
  height: 8px;
  background: #f0f2f5;
  border-radius: 4px;
  overflow: hidden;
}
.weight-bar {
  height: 100%;
  border-radius: 4px;
  transition: width 0.3s ease;
  max-width: 100%;
}
.weight-total {
  margin-top: 20px;
  font-size: 15px;
  font-weight: 600;
  padding: 10px 16px;
  border-radius: 6px;
  display: inline-block;
}
.total-ok { background: #f0f9eb; color: #67c23a; }
.total-err { background: #fef0f0; color: #f56c6c; }
</style>
