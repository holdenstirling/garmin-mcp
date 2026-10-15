// Read-only plan link for a coach or training partner.
import { getJSON, sendJSON } from '@/lib/api'
import { counted } from '@/lib/usage'

export const getShare = () => getJSON<{ url: string | null }>('/api/share')
export const createShare = () => counted(sendJSON<{ url: string }>('POST', '/api/share'), 'share', { what: 'profile' })
export const stopShare = () => sendJSON<{ url: null }>('DELETE', '/api/share')
