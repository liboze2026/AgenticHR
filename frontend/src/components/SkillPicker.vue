<template>
  <el-autocomplete
    v-model="inputValue"
    :fetch-suggestions="querySkills"
    :placeholder="placeholder"
    :trigger-on-focus="false"
    clearable
    :debounce="300"
    @select="onSelect"
    @keyup.enter="onEnter"
    class="skill-picker"
  >
    <template #default="{ item }">
      <div class="skill-suggestion">
        <span class="skill-name">{{ item.canonical_name }}</span>
        <el-tag size="small" :type="tagType(item.category)">{{ item.category }}</el-tag>
        <span v-if="item.aliases?.length" class="skill-aliases">
          ({{ item.aliases.join(', ') }})
        </span>
      </div>
    </template>
  </el-autocomplete>
</template>

<script setup>
import { ref, watch } from 'vue'
import { skillsApi } from '../api'

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '输入技能名, 按回车添加...' },
})
const emit = defineEmits(['update:modelValue', 'select'])

const inputValue = ref(props.modelValue)

watch(() => props.modelValue, (v) => { inputValue.value = v })

async function querySkills(query, cb) {
  if (!query) return cb([])
  try {
    const resp = await skillsApi.list({ search: query, limit: 10 })
    cb(resp.items || [])
  } catch (e) {
    cb([])
  }
}

function onSelect(item) {
  inputValue.value = item.canonical_name
  emit('update:modelValue', item.canonical_name)
  emit('select', item)
}

function onEnter() {
  if (!inputValue.value) return
  emit('update:modelValue', inputValue.value)
  emit('select', { canonical_name: inputValue.value, is_new: true })
}

function tagType(cat) {
  const map = { language: 'primary', framework: 'success', cloud: 'warning',
                database: 'info', tool: '', soft: 'danger', domain: 'primary' }
  return map[cat] || ''
}
</script>

<style scoped>
.skill-picker { width: 100%; }
.skill-suggestion { display: flex; align-items: center; gap: 8px; }
.skill-name { font-weight: 500; }
.skill-aliases { color: #909399; font-size: 12px; }
</style>
