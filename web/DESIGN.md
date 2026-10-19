# rabbt design rules

rabbt is used on a phone, often outdoors, right before or after a workout. Every screen should
be readable at arm's length and obvious about what to do next. These rules apply to every new
screen and every change. Nothing gets removed to follow them; things get grouped, spaced and
ordered instead.

## The five rules

1. **One thing first.** A screen opens with the one thing to do now. It gets the only filled
   button on the screen (`<Button variant="primary">`). Everything else is a secondary, ghost or
   text button.
2. **Readable at arm's length.** Body text is 16px. Nothing is smaller than 13px (`text-caption`).
   Icons are 20px in rows and buttons, 24px in the tab bar. Labels are sentence case. Never use
   tracked ALL-CAPS or monospace labels.
3. **Room to breathe.** Use 20px page gutters and 28px between sections. Cards get 16 to 20px of
   padding. Tap targets are at least 44px, and the main action is 48px. Nothing overlaps or gets
   cut off at 320px wide.
4. **Sections, not piles.** Group related things under a plain heading (`<Section>`), with a
   "See all" link when there's more. Use a card only for something you act on, like a workout, a
   post, a race or a form. Lists of rows go in one card with dividers, not one card per row.
5. **Say what it is.** Every tab has a big title and one line saying what it's for. Icons get a
   word next to them wherever there's room. Buttons say what happens ("Save workout", not "OK").

## Tokens

All sizes are in rem, so they follow the iPhone's Text Size setting. The root is 17px.

| Type token | Size | Use |
|---|---|---|
| `text-caption` | 13px | the smallest text: stat labels, timestamps, footnotes |
| `text-meta` | 14px | row subtitles, helper text, chips, the label above a group in a card |
| `text-small` | 15px | descriptions, secondary lines, segmented controls |
| `text-body` | 16px | default text, buttons, row titles |
| `text-body-lg` | 17px | list titles, inputs |
| `text-lead` | 18px | card titles |
| `text-title-sm` | 20px | section headings (`.section-title`, sans, semibold) |
| `text-title` | 22px | sheet titles, big numbers in rows |
| `text-title-md` / `text-title-lg` | 24 / 26px | the rabbt wordmark, big card headings |
| `text-display-sm` | 28px | display-font headings inside a page |
| `text-display` | 30px | the screen title (display font) |
| `text-display-lg/xl/2xl` | 34 / 38 / 44px | hero numbers, celebrations |

Don't write `text-[0.8rem]` or `text-[13px]`; `tests/test_design_tokens.py` rejects arbitrary
sizes. SVG chart text is the one exception.

**Spacing** is an 8px rhythm (`--spacing` is 4px, so `gap-2` = 8px):

| Gap | Where |
|---|---|
| `gap-7` (28px) | between sections on a screen (the `Screen` body does this for you) |
| `gap-3` (12px) | between a heading and its content, and between cards in a list |
| `px-5` (20px) | page gutters |
| `p-4` to `p-5` | card padding |
| `py-3` | rows, `min-h-14` (56px) |

**Radii:**

| Class | Size | Use |
|---|---|---|
| `rounded-full` | full | chips and pills |
| `rounded-lg` | 14px | inner tiles and inputs |
| `rounded-xl` | 20px | cards |
| `rounded-2xl` | 24px | sheets and hero cards |

**Color:** the forest-green brand on warm paper (`--bg`, `--bg-surface`). Use `--text` for
content, `--text-secondary` for supporting lines and `--text-muted` for the quietest text. All of
them are at least 4.5:1 on every surface in light and dark. Borders use `--border`. Only the main
action and the current tab use the filled accent.

## Building blocks

| Component | Where it lives | What it's for |
|---|---|---|
| `Screen` | `components/plan/ui.tsx` | Every full page and tab page. On a tab you get the compact top bar (rabbt mark and header icons), then the big title and its purpose line, which scroll away; once they're gone the bar shows the page name. Pass `subtitle` for the purpose line. |
| `Section`, `SeeAll` | `components/ui/section.tsx` | A heading, an optional one-line description, an optional "See all", then content. |
| `ListRow` | `components/ui/section.tsx` | A 56px row: icon, title, subtitle, a value or chevron. Put rows inside a `Card` for dividers. |
| `Card` | `components/plan/ui.tsx` | The grouped surface (20px radius, border, light shadow). |
| `Field`, `Chip`, `OptionCard`, `inputCls` | `components/plan/ui.tsx` | Form parts sized for thumbs. |
| `Button` | `components/ui/button.tsx` | 44px by default. Primary is 48px and semibold; `size="sm"` still has a 44px hit area. |
| `Sheet` | `components/ui/Sheet.tsx` | Bottom sheets: a title that wraps, 20px padding, a pinned footer for the action. |
| `EmptyState`, `ErrorState` | `components/ui` | Say what's missing and offer one button that fixes it. |
| `SectionLabel` | `components/ui/brand.tsx` | A plain heading when there's no action or description. |

## Copy

- Sentence case everywhere ("Up next", not "UP NEXT").
- Use plain verbs and name things by what people know ("Connect your watch", not "Integrations").
- Don't join three or more facts with dots on one line ("1h 45m · 28.6 mi · Long · Z2"). Use
  labeled stats or two short lines instead. Two short facts with one dot are fine.
- The app and the coach are both "rabbt", lowercase, even at the start of a sentence.
- An empty screen says what goes there and offers the button that fills it.

## Check before you ship

- Check 320px and 430px, in light and dark, with the audit script from the mobile pass.
- No horizontal scroll, nothing cut off, no overlapping, every tap target at least 44px.
- Text fields are at least 16px so iOS doesn't zoom.
- One filled button per screen.
