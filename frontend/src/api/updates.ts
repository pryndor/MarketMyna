import { apiClient } from './client'

/** How this copy was installed: a git checkout, a release zip, or pipx / pip. */
export type InstallKind = 'source' | 'zip' | 'package'

/** A git checkout's commit against GitHub's main branch. */
export interface CodeStatus {
  local_sha: string
  remote_sha: string
  remote_date: string | null
  message: string | null
  url: string | null
  update_available: boolean
}

export interface UpdateCheck {
  current: string
  /** Latest release version on GitHub (null: none published yet). */
  latest: string | null
  /** A newer release, or (git checkout) newer code on main. */
  update_available: boolean
  release_available?: boolean
  code?: CodeStatus | null
  repo_url: string
  install: InstallKind
  /** What to run to update this install. */
  commands: string[]
  releases_url: string
  release?: null | { version: string; name: string; url: string; published_at: string | null; notes: string }
  error: string | null
  checked_at: number | null
  /** A git checkout or pipx / pip install can update itself (Update now). */
  can_apply?: boolean
  settings?: UpdateSettings
}

export interface UpdateSettings {
  /** How often the server checks GitHub on its own: 0 (off), 5, 60 or 120 minutes. */
  interval_minutes: number
}

export interface ApplyResult {
  updated: boolean
  restarting: boolean
  log: string[]
}

/** This copy against github.com/pryndor/MarketMyna: its releases and (git checkout) the main branch. */
export async function checkUpdates(force = false): Promise<UpdateCheck> {
  return (await apiClient.get<UpdateCheck>('/system/updates', { params: { force } })).data
}

/** What the server's own background check found last (never calls GitHub). */
export async function getUpdateStatus(): Promise<UpdateCheck> {
  return (await apiClient.get<UpdateCheck>('/system/updates/status')).data
}

export async function saveUpdateSettings(settings: UpdateSettings): Promise<UpdateSettings> {
  return (await apiClient.put<UpdateSettings>('/system/updates/settings', settings)).data
}

/** Install the update and restart the app (can take a few minutes). */
export async function applyUpdate(): Promise<ApplyResult> {
  return (await apiClient.post<ApplyResult>('/system/updates/apply', undefined, { timeout: 15 * 60_000 })).data
}
