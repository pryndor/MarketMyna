import axios from 'axios'
import { UNAUTHORIZED_EVENT } from './auth'

// Relative base URL: in dev, vite.config.ts proxies /api/* to the backend
// (no CORS setup needed); in production the API serves the built frontend
// itself, so /api/* is on the same origin. Auth is an
// HttpOnly session cookie the browser sends on its own.
export const apiClient = axios.create({
  baseURL: '/api/v1',
})

apiClient.interceptors.response.use(undefined, (error) => {
  if (axios.isAxiosError(error) && error.response?.status === 401) {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  }
  return Promise.reject(error)
})
