// F4 Boss IM Intake API client
import api from './index'

export const intakeApi = {
  listIntakeCandidates: (params) => api.get('/intake/candidates', { params }),
  getIntakeCandidate: (id) => api.get(`/intake/candidates/${id}`),
  patchIntakeSlot: (id, value) => api.put(`/intake/slots/${id}`, { value }),
  abandonCandidate: (id) => api.post(`/intake/candidates/${id}/abandon`),
  forceComplete: (id) => api.post(`/intake/candidates/${id}/force-complete`),
  getSchedulerStatus: () => api.get('/intake/scheduler/status'),
  pauseScheduler: () => api.post('/intake/scheduler/pause'),
  resumeScheduler: () => api.post('/intake/scheduler/resume'),
  tickNow: () => api.post('/intake/scheduler/tick-now'),
  startConversation: (id) => api.post(`/intake/candidates/${id}/start-conversation`),
}

// Named exports for direct import
export const listIntakeCandidates = intakeApi.listIntakeCandidates
export const getIntakeCandidate = intakeApi.getIntakeCandidate
export const patchIntakeSlot = intakeApi.patchIntakeSlot
export const abandonCandidate = intakeApi.abandonCandidate
export const forceComplete = intakeApi.forceComplete
export const getSchedulerStatus = intakeApi.getSchedulerStatus
export const pauseScheduler = intakeApi.pauseScheduler
export const resumeScheduler = intakeApi.resumeScheduler
export const tickNow = intakeApi.tickNow
export const startConversation = intakeApi.startConversation

export default intakeApi
