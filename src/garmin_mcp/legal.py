"""Static privacy policy and terms pages for Rabbit (needed by OAuth providers such as Oura)."""

from __future__ import annotations

from html import escape

UPDATED = "October 14, 2026"


def _page(title: str, body: str, contact: str) -> str:
    who = (f'<a href="mailto:{escape(contact)}">{escape(contact)}</a>' if contact
           else "the person who invited you to Rabbit")
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Rabbit · {escape(title)}</title>
<style>:root{{color-scheme:light dark}}body{{margin:0;font:15px/1.55 system-ui,-apple-system,sans-serif;background:Canvas;color:CanvasText}}
main{{max-width:680px;margin:0 auto;padding:28px 18px 60px}}h1{{font-size:1.6rem;margin:0 0 4px}}h2{{font-size:1.05rem;margin:26px 0 6px}}
.sub{{opacity:.7;margin:0 0 18px}}li{{margin:4px 0}}a{{color:#2f7d5b}}</style></head><body><main>
<h1>{escape(title)}</h1><p class=sub>Rabbit training coach · updated {UPDATED}</p>
{body.replace("{CONTACT}", who)}
</main></body></html>"""


PRIVACY = """
<p>Rabbit is a small, private training app used by invited athletes and their coaches. This page explains what it stores and why.</p>
<h2>What Rabbit collects</h2>
<ul>
<li><b>Your Google account</b>: name, email and profile picture, to sign you in. Only invited accounts can use Rabbit.</li>
<li><b>Garmin Connect</b> (when you connect it): workouts, heart rate, sleep and similar training data, and the planned workouts Rabbit sends to your watch.</li>
<li><b>Oura</b> (when you connect it): readiness, sleep, heart rate variability, resting heart rate and daily activity summaries. Oura workouts are not imported; workouts come from Garmin only.</li>
<li><b>Google Calendar</b> (when you connect it, read-only): event times, used to spot busy days and travel.</li>
<li><b>What you enter</b>: your profile, goals, races, gear, photo, chats and coach messages.</li>
</ul>
<h2>How it's used</h2>
<ul>
<li>To build and adjust your training plan, show your stats and progress, and power the AI coach.</li>
<li>Chats with the AI coach are processed by Anthropic's API. <b>Oura data is never sent to the AI coach</b>: it is only shown in the app and used by fixed rules (for example, easing your plan after poor recovery).</li>
<li>Coaches you invite can see your plan, races, stats and anything you share with them. Your chats with the AI coach stay private unless you turn on sharing.</li>
<li>Rabbit does not sell your data, show ads, or share it with anyone else.</li>
</ul>
<h2>Storage and security</h2>
<p>Data is stored encrypted on a private Google Cloud server. Connection tokens for Garmin, Oura and Google Calendar are encrypted and used only to read your data (and, for Garmin, to send planned workouts you ask for).</p>
<h2>Your choices</h2>
<ul>
<li>Disconnect Garmin, Oura or Google Calendar at any time in Settings; Rabbit stops reading from them and deletes the stored tokens.</li>
<li>Ask for a copy or deletion of your data by contacting {CONTACT}.</li>
</ul>
<h2>Contact</h2><p>Questions: {CONTACT}.</p>
"""

TERMS = """
<p>By using Rabbit you agree to these terms.</p>
<h2>What Rabbit is</h2>
<p>Rabbit is a personal training tool offered free to invited users, as is, without warranties. It may change or stop at any time.</p>
<h2>Not medical advice</h2>
<p>Training plans, AI coach replies and recovery insights are general guidance, not medical advice. Check with a doctor before starting or changing training, and stop if you feel unwell or injured. You are responsible for how you train.</p>
<h2>Your account</h2>
<ul>
<li>Use Rabbit only with your own accounts and data, and keep your sign-in secure.</li>
<li>Don't misuse the service, try to access other people's data, or overload it.</li>
</ul>
<h2>Connected services</h2>
<p>Garmin, Oura, Google and Anthropic have their own terms, which also apply when you connect them. Rabbit uses their data only as described in the <a href="/app/privacy">privacy policy</a>.</p>
<h2>Liability</h2>
<p>To the extent the law allows, Rabbit's operator isn't liable for injuries, lost data or other losses from using the app.</p>
<h2>Contact</h2><p>Questions: {CONTACT}.</p>
"""


def privacy(contact: str = "") -> str:
    return _page("Privacy policy", PRIVACY, contact)


def terms(contact: str = "") -> str:
    return _page("Terms of service", TERMS, contact)


__all__ = ["privacy", "terms"]
