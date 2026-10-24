import { apiClient } from './client'

// Mirrors src/notifiers/settings_schema.py's CHANNELS - single source of
// truth on the backend, kept in sync here by hand (small, stable list).
export type FieldKind = 'text' | 'password' | 'secret_list' | 'int' | 'float' | 'bool' | 'list' | 'multiline'

export const isSecretKind = (kind: FieldKind) => kind === 'password' || kind === 'secret_list'

export interface FieldSpec {
  attr: string
  label: string
  kind: FieldKind
}

interface ChannelSpec {
  name: string
  fields: FieldSpec[]
}

export const NOTIFICATION_CHANNELS: ChannelSpec[] = [
  { name: 'Telegram', fields: [
    { attr: 'telegram_bot_token', label: 'Bot token', kind: 'password' },
    { attr: 'telegram_chat_id', label: 'Chat ID (send /start to your bot to get it; comma-separate several)', kind: 'text' },
    { attr: 'telegram_message_thread_id', label: 'Topic ID (optional, for forum groups)', kind: 'text' },
  ] },
  { name: 'WhatsApp', fields: [
    { attr: 'whatsapp_phone', label: 'Your WhatsApp number with country code (e.g. +919876543210)', kind: 'text' },
    { attr: 'whatsapp_callmebot_apikey', label: "CallMeBot API key (message +34 644 51 95 23 'I allow callmebot to send me messages')", kind: 'password' },
  ] },
  { name: 'Twilio SMS/WhatsApp', fields: [
    { attr: 'twilio_account_sid', label: 'Account SID', kind: 'text' },
    { attr: 'twilio_auth_token', label: 'Auth token', kind: 'password' },
    { attr: 'twilio_from', label: 'From number (e.g. +15551234567, or whatsapp:+14155238886)', kind: 'text' },
    { attr: 'twilio_to', label: 'To numbers (comma-separated; prefix whatsapp: for WhatsApp)', kind: 'list' },
  ] },
  { name: 'Discord', fields: [
    { attr: 'discord_webhook_url', label: 'Webhook URL', kind: 'text' },
  ] },
  { name: 'Slack', fields: [
    { attr: 'slack_webhook_url', label: 'Webhook URL', kind: 'text' },
  ] },
  { name: 'Email', fields: [
    { attr: 'email_sender', label: 'Sender address', kind: 'text' },
    { attr: 'email_reports_sender', label: 'Reports & alerts sender (blank = sender address)', kind: 'text' },
    { attr: 'email_username', label: 'SMTP username (blank = sender address; Gmail send-as: your Gmail)', kind: 'text' },
    { attr: 'email_password', label: 'Password / app password', kind: 'password' },
    { attr: 'email_receivers', label: 'Recipients (comma-separated)', kind: 'list' },
    { attr: 'email_smtp_server', label: 'SMTP server (blank = auto-detect)', kind: 'text' },
    { attr: 'email_smtp_port', label: 'SMTP port (blank = auto-detect)', kind: 'int' },
    { attr: 'email_smtp_ssl', label: 'Force SSL (unchecked = auto-detect)', kind: 'bool' },
  ] },
  { name: 'DingTalk', fields: [
    { attr: 'dingtalk_webhook_url', label: 'Webhook URL', kind: 'text' },
    { attr: 'dingtalk_secret', label: 'Secret (optional signing)', kind: 'password' },
  ] },
  { name: 'Feishu', fields: [
    { attr: 'feishu_webhook_url', label: 'Webhook URL', kind: 'text' },
    { attr: 'feishu_webhook_secret', label: 'Secret (optional signing)', kind: 'password' },
  ] },
  { name: 'WeChat', fields: [
    { attr: 'wechat_webhook_url', label: 'Group robot webhook URL', kind: 'text' },
  ] },
  { name: 'Pushover', fields: [
    { attr: 'pushover_user_key', label: 'User key', kind: 'text' },
    { attr: 'pushover_api_token', label: 'API token', kind: 'password' },
  ] },
  { name: 'ntfy', fields: [
    { attr: 'ntfy_url', label: 'Topic URL (e.g. https://ntfy.sh/mytopic)', kind: 'text' },
    { attr: 'ntfy_token', label: 'Access token (optional)', kind: 'password' },
  ] },
  { name: 'Gotify', fields: [
    { attr: 'gotify_url', label: 'Server URL', kind: 'text' },
    { attr: 'gotify_token', label: 'App token', kind: 'password' },
  ] },
  { name: 'PushPlus', fields: [
    { attr: 'pushplus_token', label: 'Token', kind: 'password' },
    { attr: 'pushplus_topic', label: 'Topic (optional, for group push)', kind: 'text' },
  ] },
  { name: 'ServerChan3', fields: [
    { attr: 'serverchan3_sendkey', label: 'SendKey', kind: 'password' },
  ] },
  { name: 'AstrBot', fields: [
    { attr: 'astrbot_url', label: 'Instance URL', kind: 'text' },
    { attr: 'astrbot_token', label: 'Token (optional)', kind: 'password' },
  ] },
  { name: 'Microsoft Teams', fields: [
    { attr: 'teams_webhook_url', label: "Workflows webhook URL (Teams channel > Workflows > 'Post to a channel when a webhook request is received')", kind: 'text' },
  ] },
  { name: 'Google Chat', fields: [
    { attr: 'google_chat_webhook_url', label: 'Space webhook URL (Space > Apps & integrations > Webhooks)', kind: 'text' },
  ] },
  { name: 'Matrix', fields: [
    { attr: 'matrix_homeserver', label: 'Homeserver URL (e.g. https://matrix.org)', kind: 'text' },
    { attr: 'matrix_access_token', label: 'Access token', kind: 'password' },
    { attr: 'matrix_room_id', label: 'Room ID (e.g. !abc123:matrix.org)', kind: 'text' },
  ] },
  { name: 'Signal', fields: [
    { attr: 'signal_api_url', label: 'signal-cli REST API URL (e.g. http://localhost:8080)', kind: 'text' },
    { attr: 'signal_number', label: 'Sending number linked to signal-cli (e.g. +919876543210)', kind: 'text' },
    { attr: 'signal_recipients', label: 'Recipients (comma-separated numbers or group IDs)', kind: 'list' },
  ] },
  { name: 'Bark (iOS)', fields: [
    { attr: 'bark_url', label: 'Device URL from the Bark app (e.g. https://api.day.app/yourkey)', kind: 'password' },
  ] },
  { name: 'Pushbullet', fields: [
    { attr: 'pushbullet_token', label: 'Access token', kind: 'password' },
  ] },
  { name: 'Apprise', fields: [
    { attr: 'apprise_urls', label: "Apprise URLs for 100+ other services (comma-separated; needs 'pip install apprise')", kind: 'list' },
  ] },
  { name: 'Webhook', fields: [
    { attr: 'webhook_url', label: 'URL', kind: 'text' },
    { attr: 'webhook_headers', label: 'Extra headers (JSON, e.g. {"Authorization": "Bearer x"})', kind: 'multiline' },
  ] },
]

// A secret field comes back as {is_set: bool}, never its raw value.
export type FieldValue = string | number | boolean | string[] | null | { is_set: boolean }

type NotificationsResponse = Record<string, Record<string, FieldValue>>

export function isSecretValue(value: FieldValue): value is { is_set: boolean } {
  return typeof value === 'object' && value !== null && 'is_set' in value
}

export async function getNotificationSettings(): Promise<NotificationsResponse> {
  const res = await apiClient.get<NotificationsResponse>('/system-config/notifications')
  return res.data
}

export async function updateNotificationSettings(
  overrides: Record<string, unknown>,
): Promise<NotificationsResponse> {
  const res = await apiClient.put<NotificationsResponse>('/system-config/notifications', overrides)
  return res.data
}

export interface TestNotificationsResult {
  configured_channels: string[]
  results: Record<string, boolean>
  message?: string
}

export async function testNotificationSettings(
  overrides: Record<string, unknown>,
): Promise<TestNotificationsResult> {
  const res = await apiClient.post<TestNotificationsResult>(
    '/system-config/notifications/test',
    overrides,
  )
  return res.data
}

export interface NotificationRouting {
  channels: string[]
  purposes: Array<{ id: string; label: string; description: string }>
  /** purpose -> channels; an empty list means every configured channel */
  routes: Record<string, string[]>
}

export async function getNotificationRouting(): Promise<NotificationRouting> {
  return (await apiClient.get<NotificationRouting>('/system-config/notification-routing')).data
}

export async function updateNotificationRouting(routes: Record<string, string[]>): Promise<NotificationRouting> {
  return (await apiClient.put<NotificationRouting>('/system-config/notification-routing', routes)).data
}
