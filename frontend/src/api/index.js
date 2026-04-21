import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,   // 120s — LLM 抽取/评分类调用经常 30-90s
})

// 请求拦截器：自动带 Token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器
api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const msg = error.response?.data?.detail || error.message || '请求失败'
    console.error('API Error:', msg)
    // 401 → token失效，跳转登录
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  }
)

// 简历 API
export const resumeApi = {
  list: (params) => api.get('/resumes/', { params }),
  get: (id) => api.get(`/resumes/${id}`),
  create: (data) => api.post('/resumes/', data),
  batchCreate: (data) => api.post('/resumes/batch', data),
  update: (id, data) => api.patch(`/resumes/${id}`, data),
  delete: (id) => api.delete(`/resumes/${id}`),
  clearAll: () => api.delete('/resumes/clear-all'),
  aiParseSingle: (id) => api.post(`/resumes/${id}/ai-parse`),
  aiParseAll: () => api.post('/resumes/ai-parse-all'),
  aiParseStatus: () => api.get('/resumes/ai-parse-status'),
  upload: (file) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post('/resumes/upload', formData)
  },
}

// 岗位 API
export const jobApi = {
  list: (params) => api.get('/screening/jobs', { params }),
  get: (id) => api.get(`/screening/jobs/${id}`),
  create: (data) => api.post('/screening/jobs', data),
  update: (id, data) => api.patch(`/screening/jobs/${id}`, data),
  delete: (id) => api.delete(`/screening/jobs/${id}`),
  screen: (jobId, resumeIds) => api.post(`/screening/jobs/${jobId}/screen`, resumeIds),
  parseJd: (jdText) => api.post('/screening/jobs/parse-jd', { jd_text: jdText }),
}

// 面试 API
export const schedulingApi = {
  listInterviewers: () => api.get('/scheduling/interviewers'),
  createInterviewer: (data) => api.post('/scheduling/interviewers', data),
  updateInterviewer: (id, data) => api.patch(`/scheduling/interviewers/${id}`, data),
  deleteInterviewer: (id) => api.delete(`/scheduling/interviewers/${id}`),
  addAvailability: (data) => api.post('/scheduling/availability', data),
  getAvailability: (id) => api.get(`/scheduling/availability/${id}`),
  matchSlots: (data) => api.post('/scheduling/match-slots', data),
  listInterviews: (params) => api.get('/scheduling/interviews', { params }),
  createInterview: (data) => api.post('/scheduling/interviews', data),
  getInterview: (id) => api.get(`/scheduling/interviews/${id}`),
  updateInterview: (id, data) => api.patch(`/scheduling/interviews/${id}`, data),
  cancelInterview: (id) => api.post(`/scheduling/interviews/${id}/cancel`),
  deleteInterview: (id) => api.delete(`/scheduling/interviews/${id}`),
  clearAllInterviews: () => api.delete('/scheduling/interviews/clear-all'),
  askInterviewerTime: (id) => api.post(`/scheduling/interviews/${id}/ask-time`),
  getFreeBusy: (interviewerId, days = 5) => api.get(`/scheduling/interviewers/${interviewerId}/freebusy`, { params: { days } }),
}

// 会议 API
export const meetingApi = {
  autoCreate: (interviewId) => api.post('/meeting/auto-create', null, { params: { interview_id: interviewId } }),
}

// 通知 API
export const notificationApi = {
  send: (data) => api.post('/notification/send', data),
  listLogs: (params) => api.get('/notification/logs', { params }),
  clearAll: () => api.delete('/notification/clear-all'),
}

// AI API — F2 已废弃 evaluate / batchEvaluate（路由 410 Gone）
// 评分用 matchingApi.score / matchingApi.recomputeJob / matchingApi.recomputeResume
export const aiApi = {
  status: () => api.get('/ai-evaluation/status'),
}

// 能力模型 API (F1)
export const competencyApi = {
  get: (jobId) => api.get(`/screening/jobs/${jobId}/competency`),
  extract: (jobId, jdText) => api.post(`/screening/jobs/${jobId}/competency/extract`, jdText ? { jd_text: jdText } : {}),
  manual: (jobId, flatFields) => api.post(`/screening/jobs/${jobId}/competency/manual`, { flat_fields: flatFields }),
  saveDraft: (jobId, model) => api.put(`/screening/jobs/${jobId}/competency/save`, { competency_model: model }),
  approve: (jobId, model) => api.post(`/screening/jobs/${jobId}/competency/approve`, { competency_model: model }),
}

// HITL API (F1)
export const hitlApi = {
  list: (params) => api.get('/hitl/tasks', { params }),
  get: (id) => api.get(`/hitl/tasks/${id}`),
  approve: (id, note = '') => api.post(`/hitl/tasks/${id}/approve`, { note }),
  reject: (id, note) => api.post(`/hitl/tasks/${id}/reject`, { note }),
  edit: (id, editedPayload, note = '') => api.post(`/hitl/tasks/${id}/edit`, { edited_payload: editedPayload, note }),
}

// 技能库 API (F1)
export const skillsApi = {
  list: (params) => api.get('/skills', { params }),
  get: (id) => api.get(`/skills/${id}`),
  create: (data) => api.post('/skills', data),
  update: (id, data) => api.put(`/skills/${id}`, data),
  merge: (id, mergeIntoId) => api.post(`/skills/${id}/merge`, { merge_into_id: mergeIntoId }),
  delete: (id) => api.delete(`/skills/${id}`),
  categories: () => api.get('/skills/categories'),
  autoClassify: () => api.post('/skills/auto-classify'),
}

// Boss API
export const bossApi = {
  status: () => api.get('/boss/status'),
  greet: (data) => api.post('/boss/greet', data),
  collect: () => api.post('/boss/collect'),
}

// 健康检查
export const healthApi = {
  check: () => api.get('/health'),
}

export const settingsApi = {
  getScoringWeights: () => api.get('/settings/scoring-weights'),
  saveScoringWeights: (data) => api.put('/settings/scoring-weights', data),
}

// 匹配 API (F2)
export const matchingApi = {
  score: (resume_id, job_id) => api.post('/matching/score', { resume_id, job_id }),
  listByJob: (job_id, { page = 1, page_size = 20, tag } = {}) =>
    api.get('/matching/results', { params: { job_id, page, page_size, tag } }),
  listByResume: (resume_id) => api.get('/matching/results', { params: { resume_id } }),
  recomputeJob: (job_id) => api.post('/matching/recompute', { job_id }),
  recomputeResume: (resume_id) => api.post('/matching/recompute', { resume_id }),
  recomputeStatus: (task_id) => api.get(`/matching/recompute/status/${task_id}`),
  // per-(resume, job) action: 'passed' / 'rejected' / null
  setAction: (id, action) => api.patch(`/matching/results/${id}/action`, { action }),
  listPassedForJob: (job_id) => api.get(`/matching/passed-resumes/${job_id}`),
}

export default api
