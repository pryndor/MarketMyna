import { apiClient } from './client'

export interface PushDevice {
  id: number
  label: string
  service: string
  created_at: string | null
  last_success_at: string | null
}

export async function getVapidPublicKey(): Promise<string> {
  return (await apiClient.get<{ public_key: string }>('/push/vapid-public-key')).data.public_key
}

export async function listPushDevices(): Promise<PushDevice[]> {
  return (await apiClient.get<PushDevice[]>('/push/subscriptions')).data
}

export async function savePushSubscription(subscription: PushSubscriptionJSON, label: string): Promise<PushDevice> {
  return (await apiClient.post<PushDevice>('/push/subscriptions', { ...subscription, label })).data
}

export async function removePushEndpoint(endpoint: string): Promise<void> {
  await apiClient.post('/push/unsubscribe', { endpoint })
}

export async function deletePushDevice(id: number): Promise<void> {
  await apiClient.delete(`/push/subscriptions/${id}`)
}

export async function sendTestPush(): Promise<{ sent: boolean; message: string }> {
  return (await apiClient.post<{ sent: boolean; message: string }>('/push/test')).data
}
