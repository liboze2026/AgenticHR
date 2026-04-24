// F5 intake settings API client — HR master switch + target gate
import api from './index'

export const intakeSettingsApi = {
  getIntakeSettings: () => api.get('/intake/settings'),
  updateIntakeSettings: ({ enabled, target_count } = {}) => {
    const body = {}
    if (typeof enabled === 'boolean') body.enabled = enabled
    if (typeof target_count === 'number') body.target_count = target_count
    return api.put('/intake/settings', body)
  },
}

export const getIntakeSettings = intakeSettingsApi.getIntakeSettings
export const updateIntakeSettings = intakeSettingsApi.updateIntakeSettings

export default intakeSettingsApi
