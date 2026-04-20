import { ref } from 'vue'
import { hitlApi } from '../api'

export const hitlPendingCount = ref(0)

export async function refreshHitlCount() {
  try {
    const resp = await hitlApi.list({ status: 'pending', limit: 1 })
    hitlPendingCount.value = resp.total || 0
  } catch {}
}
