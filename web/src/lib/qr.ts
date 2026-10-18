// A small QR code encoder (byte mode, error correction M, versions 1-8, which fits links of
// up to 150 bytes; every version and mask was checked against a decoder) for "Add me on Rabbit". No dependency: the matrix is drawn as SVG by
// components/friends/QrCode. Follows ISO/IEC 18004: Reed-Solomon over GF(256), the eight masks
// scored by the four penalty rules, format bits with BCH(15,5) and version bits for v7+.

// Per version (index 1..10) at level M: [total codewords, ec codewords per block, blocks in group 1,
// data codewords per block in group 1, blocks in group 2, data codewords per block in group 2].
const M_TABLE: number[][] = [
  [],
  [26, 10, 1, 16, 0, 0], [44, 16, 1, 28, 0, 0], [70, 26, 1, 44, 0, 0], [100, 18, 2, 32, 0, 0],
  [134, 24, 2, 43, 0, 0], [172, 16, 4, 27, 0, 0], [196, 18, 4, 31, 0, 0], [242, 22, 2, 38, 2, 39],
  [292, 22, 3, 36, 2, 37], [346, 26, 4, 43, 1, 44],
]
const MAX_VERSION = 8
const ALIGN: number[][] = [[], [], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50]]

// GF(256) with the QR polynomial 0x11d.
const EXP = new Uint8Array(512)
const LOG = new Uint8Array(256)
{
  let x = 1
  for (let i = 0; i < 255; i++) { EXP[i] = x; LOG[x] = i; x <<= 1; if (x & 0x100) x ^= 0x11d }
  for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255]
}
const mul = (a: number, b: number) => (a === 0 || b === 0 ? 0 : EXP[LOG[a] + LOG[b]])

function generator(n: number): number[] {
  let g = [1]
  for (let i = 0; i < n; i++) {
    const next = new Array(g.length + 1).fill(0)
    for (let j = 0; j < g.length; j++) { next[j] ^= g[j]; next[j + 1] ^= mul(g[j], EXP[i]) }
    g = next
  }
  return g
}

function ecc(data: number[], n: number): number[] {
  const g = generator(n)
  const r = [...data, ...new Array(n).fill(0)]
  for (let i = 0; i < data.length; i++) {
    const c = r[i]
    if (c !== 0) for (let j = 0; j < g.length; j++) r[i + j] ^= mul(g[j], c)
  }
  return r.slice(data.length)
}

function dataCapacity(v: number): number {
  const [, , b1, d1, b2, d2] = M_TABLE[v]
  return b1 * d1 + b2 * d2
}

function codewords(bytes: Uint8Array, v: number): number[] {
  const cap = dataCapacity(v)
  const bits: number[] = []
  const put = (val: number, len: number) => { for (let i = len - 1; i >= 0; i--) bits.push((val >>> i) & 1) }
  put(0b0100, 4)
  put(bytes.length, v < 10 ? 8 : 16)
  for (const b of bytes) put(b, 8)
  put(0, Math.min(4, cap * 8 - bits.length))
  while (bits.length % 8) bits.push(0)
  const data: number[] = []
  for (let i = 0; i < bits.length; i += 8) data.push(bits.slice(i, i + 8).reduce((a, b) => (a << 1) | b, 0))
  for (let pad = 0; data.length < cap; pad++) data.push(pad % 2 ? 0x11 : 0xec)
  // Split into blocks, add error correction, interleave.
  const [, ecn, b1, d1, b2, d2] = M_TABLE[v]
  const blocks: number[][] = []
  let k = 0
  for (let i = 0; i < b1; i++) { blocks.push(data.slice(k, k + d1)); k += d1 }
  for (let i = 0; i < b2; i++) { blocks.push(data.slice(k, k + d2)); k += d2 }
  const ecs = blocks.map((b) => ecc(b, ecn))
  const out: number[] = []
  for (let i = 0; i < Math.max(d1, d2); i++) for (const b of blocks) if (i < b.length) out.push(b[i])
  for (let i = 0; i < ecn; i++) for (const e of ecs) out.push(e[i])
  return out
}

type Grid = { size: number; dark: boolean[][]; fixed: boolean[][] }

function blank(v: number): Grid {
  const size = 17 + 4 * v
  return { size, dark: Array.from({ length: size }, () => new Array(size).fill(false)),
    fixed: Array.from({ length: size }, () => new Array(size).fill(false)) }
}

function set(g: Grid, r: number, c: number, on: boolean) { g.dark[r][c] = on; g.fixed[r][c] = true }

function functionPatterns(g: Grid, v: number) {
  const n = g.size
  const finder = (r0: number, c0: number) => {
    for (let r = -1; r <= 7; r++) for (let c = -1; c <= 7; c++) {
      const rr = r0 + r, cc = c0 + c
      if (rr < 0 || rr >= n || cc < 0 || cc >= n) continue
      const on = r >= 0 && r <= 6 && c >= 0 && c <= 6 && (r === 0 || r === 6 || c === 0 || c === 6 || (r >= 2 && r <= 4 && c >= 2 && c <= 4))
      set(g, rr, cc, on)
    }
  }
  finder(0, 0); finder(0, n - 7); finder(n - 7, 0)
  for (let i = 8; i < n - 8; i++) { set(g, 6, i, i % 2 === 0); set(g, i, 6, i % 2 === 0) }
  const al = ALIGN[v]
  const last = al.length - 1
  al.forEach((r, i) => al.forEach((c, j) => {
    if ((i === 0 && j === 0) || (i === 0 && j === last) || (i === last && j === 0)) return  // finders
    for (let dr = -2; dr <= 2; dr++) for (let dc = -2; dc <= 2; dc++)
      set(g, r + dr, c + dc, Math.max(Math.abs(dr), Math.abs(dc)) !== 1)
  }))
  // Reserve format areas (filled later) and the dark module.
  for (let i = 0; i < 9; i++) { if (!g.fixed[8][i]) set(g, 8, i, false); if (!g.fixed[i][8]) set(g, i, 8, false) }
  for (let i = 0; i < 8; i++) { set(g, 8, n - 1 - i, false); set(g, n - 1 - i, 8, false) }
  set(g, n - 8, 8, true)
  if (v >= 7) {
    let rem = v
    for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25)
    const bits = (v << 12) | rem
    for (let i = 0; i < 18; i++) {
      const on = ((bits >>> i) & 1) === 1
      const a = n - 11 + (i % 3), b = Math.floor(i / 3)
      set(g, a, b, on); set(g, b, a, on)
    }
  }
}

function placeData(g: Grid, cw: number[]) {
  const n = g.size
  let bit = 0
  const total = cw.length * 8
  for (let right = n - 1; right >= 1; right -= 2) {
    if (right === 6) right = 5
    for (let vert = 0; vert < n; vert++) {
      for (let j = 0; j < 2; j++) {
        const c = right - j
        const upward = ((right + 1) & 2) === 0
        const r = upward ? n - 1 - vert : vert
        if (g.fixed[r][c]) continue
        g.dark[r][c] = bit < total ? ((cw[bit >>> 3] >>> (7 - (bit & 7))) & 1) === 1 : false
        bit++
      }
    }
  }
}

const MASKS: ((r: number, c: number) => boolean)[] = [
  (r, c) => (r + c) % 2 === 0, (r) => r % 2 === 0, (_r, c) => c % 3 === 0, (r, c) => (r + c) % 3 === 0,
  (r, c) => (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0, (r, c) => ((r * c) % 2) + ((r * c) % 3) === 0,
  (r, c) => (((r * c) % 2) + ((r * c) % 3)) % 2 === 0, (r, c) => (((r + c) % 2) + ((r * c) % 3)) % 2 === 0,
]

function applyMask(g: Grid, m: number): boolean[][] {
  const f = MASKS[m]
  return g.dark.map((row, r) => row.map((on, c) => (g.fixed[r][c] ? on : on !== f(r, c))))
}

function drawFormat(dark: boolean[][], m: number) {
  const n = dark.length
  const data = (0b00 << 3) | m // level M = 00
  let rem = data
  for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537)
  const bits = ((data << 10) | rem) ^ 0x5412
  const bit = (i: number) => ((bits >>> i) & 1) === 1
  for (let i = 0; i <= 5; i++) dark[i][8] = bit(i)
  dark[7][8] = bit(6); dark[8][8] = bit(7); dark[8][7] = bit(8)
  for (let i = 9; i < 15; i++) dark[8][14 - i] = bit(i)
  for (let i = 0; i < 8; i++) dark[8][n - 1 - i] = bit(i)
  for (let i = 8; i < 15; i++) dark[n - 15 + i][8] = bit(i)
  dark[n - 8][8] = true
}

function penalty(d: boolean[][]): number {
  const n = d.length
  let p = 0
  const runs = (get: (i: number, j: number) => boolean) => {
    for (let i = 0; i < n; i++) {
      let run = 1
      for (let j = 1; j <= n; j++) {
        if (j < n && get(i, j) === get(i, j - 1)) run++
        else { if (run >= 5) p += run - 2; run = 1 }
      }
    }
  }
  runs((i, j) => d[i][j]); runs((i, j) => d[j][i])
  for (let r = 0; r < n - 1; r++) for (let c = 0; c < n - 1; c++) {
    const v = d[r][c]
    if (v === d[r][c + 1] && v === d[r + 1][c] && v === d[r + 1][c + 1]) p += 3
  }
  const pat = [true, false, true, true, true, false, true]
  const matchAt = (get: (k: number) => boolean | undefined) => {
    for (let k = 0; k < 7; k++) if (get(k) !== pat[k]) return false
    return true
  }
  const light4 = (get: (k: number) => boolean | undefined) => {
    for (let k = 0; k < 4; k++) if (get(k) === true) return false
    return true
  }
  for (let r = 0; r < n; r++) for (let c = 0; c + 7 <= n; c++) {
    if (matchAt((k) => d[r][c + k]) && (light4((k) => d[r][c - 1 - k]) || light4((k) => d[r][c + 7 + k]))) p += 40
    if (matchAt((k) => d[c + k][r]) && (light4((k) => d[c - 1 - k]?.[r]) || light4((k) => d[c + 7 + k]?.[r]))) p += 40
  }
  let darkCount = 0
  for (const row of d) for (const on of row) if (on) darkCount++
  p += Math.floor(Math.abs((darkCount * 100) / (n * n) - 50) / 5) * 10
  return p
}

/** The QR matrix for ``text`` (true = dark), or null when it's too long (over 150 bytes). */
export function qrMatrix(text: string): boolean[][] | null {
  const bytes = new TextEncoder().encode(text)
  let v = 1
  while (v <= MAX_VERSION && dataCapacity(v) < bytes.length + 2) v++
  if (v > MAX_VERSION) return null
  const g = blank(v)
  functionPatterns(g, v)
  placeData(g, codewords(bytes, v))
  let best: boolean[][] | null = null
  let bestScore = Infinity
  for (let m = 0; m < 8; m++) {
    const d = applyMask(g, m)
    drawFormat(d, m)
    const s = penalty(d)
    if (s < bestScore) { bestScore = s; best = d }
  }
  return best
}
