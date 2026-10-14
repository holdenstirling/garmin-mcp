// Read-only plan link for a coach or training partner.
import { getJSON, sendJSON } from '@/lib/api'

export const getShare = () => getJSON<{ url: string | null }>('/api/share')
export const createShare = () => sendJSON<{ url: string }>('POST', '/api/share')
export const stopShare = () => sendJSON<{ url: null }>('DELETE', '/api/share')
