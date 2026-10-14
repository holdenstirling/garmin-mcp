// Minimal typing for the Web Speech API's SpeechRecognition (not in every TS DOM lib, and
// prefixed as webkitSpeechRecognition in Safari/Chrome). Only what the voice check-in uses.

export interface SpeechAlternative { readonly transcript: string; readonly confidence: number }
export interface SpeechResult {
  readonly length: number
  readonly isFinal: boolean
  readonly [index: number]: SpeechAlternative
}
export interface SpeechResultList { readonly length: number; readonly [index: number]: SpeechResult }
export interface SpeechResultEvent extends Event { readonly resultIndex: number; readonly results: SpeechResultList }
export interface SpeechErrorEvent extends Event { readonly error: string; readonly message?: string }

export interface SpeechRecognizer extends EventTarget {
  lang: string
  continuous: boolean
  interimResults: boolean
  maxAlternatives: number
  start(): void
  stop(): void
  abort(): void
  onresult: ((e: SpeechResultEvent) => void) | null
  onerror: ((e: SpeechErrorEvent) => void) | null
  onend: ((e: Event) => void) | null
  onstart: ((e: Event) => void) | null
}
type RecognizerCtor = new () => SpeechRecognizer
type SpeechWindow = { SpeechRecognition?: RecognizerCtor; webkitSpeechRecognition?: RecognizerCtor }

export function speechCtor(): RecognizerCtor | null {
  if (typeof window === 'undefined') return null
  const w = window as unknown as SpeechWindow
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

/** Errors that mean "no mic for you": fall back to typing. */
export const DENIED_ERRORS = new Set(['not-allowed', 'service-not-allowed', 'audio-capture', 'language-not-supported'])
