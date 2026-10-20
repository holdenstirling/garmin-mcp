// A food emoji for a fueling idea ("a banana (~25 g)" -> 🍌). Decoration only: the words stay
// next to it and the emoji is aria-hidden. First match wins, so specific foods come before
// general ones ("chocolate milk" before "milk", "rice cake" before "rice").
const RULES: [RegExp, string][] = [
  [/chocolate milk/i, '🍫'],
  [/recovery shake|plant-protein shake|shake/i, '🥤'],
  [/drink mix|sports drink|soft flask/i, '🥤'],
  [/\bgel\b/i, '⚡'],
  [/chews/i, '🍬'],
  [/banana/i, '🍌'],
  [/dates/i, '🌴'],
  [/fig bar|granola bar/i, '🍫'],
  [/applesauce/i, '🍎'],
  [/rice cake/i, '🍚'],
  [/pb&j|peanut butter/i, '🥜'],
  [/bagel/i, '🥯'],
  [/oats/i, '🥣'],
  [/yogurt/i, '🍓'],
  [/eggs?\b/i, '🍳'],
  [/hummus|wrap/i, '🌯'],
  [/pasta/i, '🍝'],
  [/rice bowl|\brice\b/i, '🍚'],
  [/potato/i, '🥔'],
  [/toast/i, '🍞'],
  [/coffee|caffein/i, '☕'],
  [/salt|sodium/i, '🧂'],
  [/water|sip|bottle/i, '💧'],
  [/milk/i, '🥛'],
  [/meal|dinner/i, '🍽️'],
  [/snack/i, '🍪'],
]

export function foodEmoji(text: string): string | null {
  for (const [re, e] of RULES) if (re.test(text)) return e
  return null
}
