// Open the rabbt chat with a prefilled message from anywhere (screens/Chat.tsx listens).
export const ASK_EVENT = 'rabbt:ask'
export function askRabbt(text: string): void {
  window.dispatchEvent(new CustomEvent(ASK_EVENT, { detail: text }))
}
