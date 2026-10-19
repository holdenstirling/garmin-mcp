import { type ClassValue, clsx } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// tailwind-merge has to know the app's type scale (globals.css @theme --text-*): otherwise it
// reads `text-body` as a text color and `cn('text-(--on-fill)', 'text-body')` drops the color.
export const TEXT_SIZES = [
  "caption", "meta", "small", "body", "body-lg", "lead", "title-sm", "title", "title-md", "title-lg",
  "display-sm", "display", "display-lg", "display-xl", "display-2xl",
] as const;

const twMerge = extendTailwindMerge({ extend: { theme: { text: [...TEXT_SIZES] } } });

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
