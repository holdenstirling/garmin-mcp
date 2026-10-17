// One in-app confirm for destructive actions (components/ui/ConfirmHost renders it), instead of
// the browser's window.confirm: same look as the rest of Rabbit, keyboard and screen reader
// friendly (alertdialog, focus on the safe choice, Escape cancels).
//
//   if (!(await confirmAsk('Delete this post?', { confirm: 'Delete', danger: true }))) return
export type ConfirmOpts = { confirm?: string; cancel?: string; danger?: boolean; detail?: string }
export type ConfirmReq = ConfirmOpts & { message: string; resolve: (ok: boolean) => void }

export const CONFIRM_EVENT = 'rabbit:confirm'

export function confirmAsk(message: string, opts: ConfirmOpts = {}): Promise<boolean> {
  return new Promise((resolve) => {
    const req: ConfirmReq = { message, ...opts, resolve }
    // No host mounted (should not happen): fall back to the browser's confirm.
    const handled = !window.dispatchEvent(new CustomEvent<ConfirmReq>(CONFIRM_EVENT, { detail: req, cancelable: true }))
    if (!handled) resolve(window.confirm(message))
  })
}
