<template>
  <div class="skill-library">
    <el-card>
      <div class="toolbar">
        <el-input v-model="searchQ" placeholder="搜索技能..." clearable
                   @clear="refresh" @keyup.enter="refresh" style="width:240px" />
        <el-select v-model="categoryFilter" clearable placeholder="所有分类"
                    @change="refresh" style="width:160px">
          <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
        </el-select>
        <el-switch v-model="pendingOnly" active-text="仅待归类" @change="refresh" />
        <el-button type="primary" @click="showCreateDialog = true">新增技能</el-button>
        <el-button v-if="selected.length > 0" type="warning" @click="batchClassify">
          批量设分类 ({{ selected.length }})
        </el-button>
        <span class="total">共 {{ total }} 条</span>
      </div>

      <el-table :data="items" v-loading="loading" border
                 @selection-change="sel => selected = sel">
        <el-table-column type="selection" width="50" :selectable="row => row.pending_classification" />
        <el-table-column label="技能" prop="canonical_name" width="180" />
        <el-table-column label="别名" min-width="200">
          <template #default="{ row }">
            <el-tag v-for="a in row.aliases" :key="a" size="small" style="margin-right:4px">{{ a }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="分类" width="120">
          <template #default="{ row }">
            <el-tag :type="tagType(row.category)">{{ row.category }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="100" prop="source" />
        <el-table-column label="使用次数" width="100" prop="usage_count" sortable />
        <el-table-column label="待归类" width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.pending_classification" type="warning">是</el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="warning" @click="openMerge(row)">合并</el-button>
            <el-button size="small" type="danger"
                        :disabled="row.source === 'seed' || row.usage_count > 0"
                        @click="doDelete(row)">删</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="showCreateDialog" title="新增技能" width="500px">
      <el-form :model="createForm" label-width="90px">
        <el-form-item label="名称"><el-input v-model="createForm.canonical_name" /></el-form-item>
        <el-form-item label="分类">
          <el-select v-model="createForm.category" style="width:100%">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="别名 (逗号)">
          <el-input v-model="createForm.aliasesStr" placeholder="py3, pyy" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog=false">取消</el-button>
        <el-button type="primary" @click="doCreate">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showEditDialog" title="编辑技能" width="500px">
      <el-form :model="editForm" label-width="90px">
        <el-form-item label="名称"><el-input v-model="editForm.canonical_name" /></el-form-item>
        <el-form-item label="分类">
          <el-select v-model="editForm.category" style="width:100%">
            <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="别名 (逗号)">
          <el-input v-model="editForm.aliasesStr" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showEditDialog=false">取消</el-button>
        <el-button type="primary" @click="doUpdate">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showMergeDialog" title="合并到另一个技能" width="500px">
      <p>把 <b>{{ mergeFrom?.canonical_name }}</b> 合并到:</p>
      <SkillPicker v-model="mergeTargetName" @select="s => mergeTargetId = s.id" />
      <template #footer>
        <el-button @click="showMergeDialog=false">取消</el-button>
        <el-button type="warning" @click="doMerge">合并</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showBatchDialog" title="批量设置分类" width="400px">
      <el-select v-model="batchCategory" placeholder="选择分类" style="width:100%">
        <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
      </el-select>
      <template #footer>
        <el-button @click="showBatchDialog=false">取消</el-button>
        <el-button type="primary" @click="doBatchClassify">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { skillsApi } from '../api'
import SkillPicker from '../components/SkillPicker.vue'

const searchQ = ref('')
const categoryFilter = ref('')
const pendingOnly = ref(false)
const items = ref([])
const categories = ref([])
const total = ref(0)
const loading = ref(false)
const selected = ref([])

const showCreateDialog = ref(false)
const createForm = ref({ canonical_name: '', category: 'uncategorized', aliasesStr: '' })

const showEditDialog = ref(false)
const editForm = ref({ id: 0, canonical_name: '', category: '', aliasesStr: '' })

const showMergeDialog = ref(false)
const mergeFrom = ref(null)
const mergeTargetName = ref('')
const mergeTargetId = ref(null)

const showBatchDialog = ref(false)
const batchCategory = ref('')

function tagType(cat) {
  return { language: 'primary', framework: 'success', cloud: 'warning',
           database: 'info', tool: '', soft: 'danger', domain: 'primary' }[cat] || ''
}

async function refresh() {
  loading.value = true
  try {
    const params = { limit: 200 }
    if (searchQ.value) params.search = searchQ.value
    if (categoryFilter.value) params.category = categoryFilter.value
    if (pendingOnly.value) params.pending = true
    const resp = await skillsApi.list(params)
    items.value = resp.items || []
    total.value = resp.total || 0
  } finally { loading.value = false }
}

async function loadCategories() {
  const resp = await skillsApi.categories()
  categories.value = resp.categories || []
}

function openEdit(row) {
  editForm.value = {
    id: row.id, canonical_name: row.canonical_name, category: row.category,
    aliasesStr: (row.aliases || []).join(', '),
  }
  showEditDialog.value = true
}

async function doCreate() {
  try {
    await skillsApi.create({
      canonical_name: createForm.value.canonical_name,
      category: createForm.value.category,
      aliases: createForm.value.aliasesStr.split(',').map(s => s.trim()).filter(Boolean),
    })
    showCreateDialog.value = false
    createForm.value = { canonical_name: '', category: 'uncategorized', aliasesStr: '' }
    ElMessage.success('已保存')
    refresh()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.message || e))
  }
}

async function doUpdate() {
  try {
    await skillsApi.update(editForm.value.id, {
      canonical_name: editForm.value.canonical_name,
      category: editForm.value.category,
      aliases: editForm.value.aliasesStr.split(',').map(s => s.trim()).filter(Boolean),
    })
    showEditDialog.value = false
    ElMessage.success('已保存')
    refresh()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.message || e))
  }
}

function openMerge(row) {
  if (row.source === 'seed') {
    ElMessage.warning('种子技能不可合并')
    return
  }
  mergeFrom.value = row
  mergeTargetName.value = ''
  mergeTargetId.value = null
  showMergeDialog.value = true
}

async function doMerge() {
  if (!mergeTargetId.value) {
    ElMessage.warning('请选择目标技能')
    return
  }
  try {
    await skillsApi.merge(mergeFrom.value.id, mergeTargetId.value)
    ElMessage.success('已合并')
    showMergeDialog.value = false
    refresh()
  } catch (e) {
    ElMessage.error('合并失败: ' + (e.message || e))
  }
}

async function doDelete(row) {
  try {
    await ElMessageBox.confirm(`删除技能 "${row.canonical_name}"?`, '确认', { type: 'warning' })
    await skillsApi.delete(row.id)
    ElMessage.success('已删除')
    refresh()
  } catch (e) {
    if (e !== 'cancel' && e?.type !== 'cancel') ElMessage.error('删除失败: ' + (e.message || e))
  }
}

function batchClassify() {
  showBatchDialog.value = true
  batchCategory.value = ''
}

async function doBatchClassify() {
  if (!batchCategory.value) return
  try {
    await Promise.all(selected.value.map(s => skillsApi.update(s.id, { category: batchCategory.value })))
    showBatchDialog.value = false
    ElMessage.success(`已更新 ${selected.value.length} 条`)
    refresh()
  } catch (e) {
    ElMessage.error('批量更新失败: ' + (e.message || e))
  }
}

onMounted(() => { loadCategories(); refresh() })
</script>

<style scoped>
.skill-library { padding: 20px; }
.toolbar { display: flex; gap: 12px; margin-bottom: 16px; align-items: center; flex-wrap: wrap; }
.total { color: #909399; margin-left: auto; }
</style>
