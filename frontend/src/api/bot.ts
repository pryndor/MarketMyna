import { apiClient } from './client'

interface CommandResult {
  text: string
  success: boolean
}

export async function sendBotCommand(text: string): Promise<CommandResult> {
  const res = await apiClient.post<CommandResult>('/bot/command', {
    text,
    platform: 'http',
    chat_id: 'http',
  })
  return res.data
}

export interface BotCommand {
  name: string
  aliases: string[]
  /** "/quote SYMBOL [market]" */
  usage: string
  description: string
  /** Heading in the reference: "Stock research", "Markets", ... */
  group: string
  /** A runnable example. */
  example: string
}

export async function getBotCommands(): Promise<BotCommand[]> {
  const res = await apiClient.get<BotCommand[]>('/bot/commands')
  return res.data
}
