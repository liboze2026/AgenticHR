import { reactive } from 'vue'

// 模块单例：跨组件生命周期持久，页面切走再回来不丢失
export const extractingJobIds = reactive(new Set())
