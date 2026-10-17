// 'smooth' unless the person asked their OS for reduced motion, then a jump. Use for every
// scrollTo / scrollIntoView that would otherwise animate.
export function smooth(): ScrollBehavior {
  try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' } catch { return 'auto' }
}
