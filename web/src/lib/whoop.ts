// WHOOP (server: whoop.py): workouts only, display + friends feed, never sent to Rabbit's AI.
// Connect goes to WHOOP's own sign-in page and back (?whoop=connected|failed).
import { sendJSON } from '@/lib/api'

export const WHOOP_CONNECT_URL = '/app/auth/whoop/start'
export const disconnectWhoop = () => sendJSON<{ connected: false }>('DELETE', '/api/whoop')
