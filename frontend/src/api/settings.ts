import { apiFetch } from './client'
import type { AppSettings } from '../types'

export function getSettings(): Promise<AppSettings> {
  return apiFetch('/settings')
}

export function updateSettings(settings: AppSettings): Promise<AppSettings> {
  return apiFetch('/settings', { method: 'PUT', body: JSON.stringify(settings) })
}
