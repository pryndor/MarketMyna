import axios from 'axios'

// Auth routes live outside /api/v1 so the backend can leave them open while
// everything else requires the session cookie.
// A timeout so a hung API shows the signed-out pages, not a loading box forever.
const authClient = axios.create({ baseURL: '/api/auth', timeout: 15_000 })

type AuthStatus = { authenticated: boolean }

export async function getAuthStatus(): Promise<AuthStatus> {
  return (await authClient.get<AuthStatus>('/status')).data
}

/** Fired by the apiClient interceptor when any call comes back 401 (e.g. the
 * session expired or was revoked), so the app signs the user out. */
export const UNAUTHORIZED_EVENT = 'marketmyna:unauthorized'
