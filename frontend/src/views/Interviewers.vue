<template>
  <div>
    <div style="display: flex; justify-content: space-between; margin-bottom: 16px">
      <h2>面试官管理</h2>
      <el-button type="primary" @click="openAdd">添加面试官</el-button>
    </div>

    <el-table :data="interviewers" stripe v-loading="loading">
      <el-table-column prop="name" label="姓名" width="120" />
      <el-table-column prop="department" label="部门" width="120" />
      <el-table-column prop="phone" label="手机号" width="140" />
      <el-table-column prop="email" label="邮箱" show-overflow-tooltip />
      <el-table-column prop="feishu_user_id" label="飞书 Open ID" show-overflow-tooltip />
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button size="small" link @click="editInterviewer(row)">编辑</el-button>
          <el-button size="small" type="danger" link @click="deleteInterviewer(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="showAdd" :title="editingId ? '编辑面试官' : '添加面试官'" width="480px">
      <el-form :model="form" label-width="100px" @submit.prevent>
        <el-form-item label="姓名" required>
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="部门">
          <el-input v-model="form.department" placeholder="可选" />
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="form.phone" placeholder="11 位中国手机号" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" placeholder="公司邮箱" />
        </el-form-item>
        <el-form-item label="飞书ID">
          <el-input v-model="form.feishu_user_id" placeholder="留空将按手机号/邮箱自动查找" />
        </el-form-item>
        <div class="form-hint">
          <el-icon><InfoFilled /></el-icon>
          <span>手机号 / 邮箱 / 飞书ID 至少填写一项。留空飞书ID 时系统会自动从飞书通讯录反查。</span>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="showAdd = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveInterviewer">
          {{ saving ? '查询飞书中…' : '保存' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { InfoFilled } from '@element-plus/icons-vue'
import { schedulingApi } from '../api'

const interviewers = ref([])
const loading = ref(false)
const showAdd = ref(false)
const editingId = ref(null)
const saving = ref(false)
const emptyForm = () => ({ name: '', department: '', phone: '', email: '', feishu_user_id: '' })
const form = ref(emptyForm())

async function loadInterviewers() {
  loading.value = true
  try {
    const data = await schedulingApi.listInterviewers()
    interviewers.value = data.items
  } catch (e) {
    console.error('listInterviewers failed:', e)
    ElMessage.error('加载面试官失败')
  } finally {
    loading.value = false
  }
}

function openAdd() {
  editingId.value = null
  form.value = emptyForm()
  showAdd.value = true
}

function editInterviewer(row) {
  editingId.value = row.id
  form.value = {
    name: row.name,
    department: row.department || '',
    phone: row.phone || '',
    email: row.email || '',
    feishu_user_id: row.feishu_user_id || '',
  }
  showAdd.value = true
}

async function saveInterviewer() {
  if (!form.value.name.trim()) {
    ElMessage.warning('请填写姓名')
    return
  }
  if (!form.value.phone && !form.value.email && !form.value.feishu_user_id) {
    ElMessage.warning('手机号 / 邮箱 / 飞书ID 至少填写一项')
    return
  }
  if (form.value.phone && !/^1[3-9]\d{9}$/.test(form.value.phone)) {
    ElMessage.warning('手机号格式不正确，需为11位中国手机号'); return
  }
  if (form.value.email && !/^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/.test(form.value.email)) {
    ElMessage.warning('邮箱格式不正确'); return
  }
  saving.value = true
  try {
    if (editingId.value) {
      await schedulingApi.updateInterviewer(editingId.value, form.value)
    } else {
      await schedulingApi.createInterviewer(form.value)
    }
    ElMessage.success(editingId.value ? '更新成功' : '添加成功')
    showAdd.value = false
    editingId.value = null
    form.value = emptyForm()
    loadInterviewers()
  } catch (e) {
    console.error('saveInterviewer failed:', e)
    if (e.response?.status === 409) {
      ElMessage.warning(e.response.data.detail)
    } else if (e.response?.status === 422) {
      const detail = e.response.data?.detail
      if (typeof detail === 'string') {
        ElMessage.warning(detail)
      } else if (Array.isArray(detail)) {
        ElMessage.warning(detail.map(d => d.msg).join('; '))
      } else {
        ElMessage.warning('输入信息有误，请检查后重试')
      }
    } else {
      ElMessage.error('保存失败: ' + (e.response?.data?.detail || '请检查网络连接'))
    }
  } finally {
    saving.value = false
  }
}

async function deleteInterviewer(row) {
  try {
    await ElMessageBox.confirm(`确定删除面试官"${row.name}"？`, '确认')
    await schedulingApi.deleteInterviewer(row.id)
    ElMessage.success('已删除')
    loadInterviewers()
  } catch (e) {
    if (e.response?.status === 409) {
      ElMessage.warning(e.response.data.detail)
    } else if (e !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

onMounted(loadInterviewers)
</script>

<style scoped>
.form-hint {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 8px 12px;
  margin: 4px 0 -8px 100px;
  background: #f4f8fd;
  border: 1px solid #d4e4f5;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.5;
  color: #5b8ec3;
}
.form-hint .el-icon {
  font-size: 14px;
  flex-shrink: 0;
  margin-top: 2px;
}
</style>
