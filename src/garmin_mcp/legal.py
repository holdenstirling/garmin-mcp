"""Rabbit's legal and trust pages: privacy policy, terms, data & security, community guidelines,
and the RabbitBot crawler page. Server-rendered, versioned, light/dark, printable.

Every factual claim is checked against the code it describes (file refs in the comments); tests
pin the ones other features rely on (test_connections, test_usage, test_tpsync, test_clubdir,
test_legal). When a fact changes, change the page and bump ``VERSION`` so people are asked to
review it again (consent.py).

Owner note (not shown to users): have a lawyer review these pages before a public launch,
especially HEALTH_DATA (Washington My Health My Data Act, Nevada SB 370, Connecticut) and the
breach sections (FTC Health Breach Notification Rule, 16 CFR Part 318).
"""

from __future__ import annotations

from html import escape

VERSION = "2026-10-21"          # consent re-prompts when this changes
UPDATED = "October 21, 2026"
OPERATOR = "Holden Ottolini"
DEFAULT_CONTACT = "holdenstirling@gmail.com"
GOVERNING = "Colorado, USA"

DOCS = {  # slug -> (title, short label)
    "privacy": ("Privacy policy", "Privacy"),
    "terms": ("Terms of service", "Terms"),
    "security": ("How rabbt keeps your data safe", "Data & security"),
    "guidelines": ("Community guidelines", "Community"),
    "health-data": ("Consumer health data privacy policy", "Health data"),
}


# The one-line data stance shown across the app and on public pages (web: lib/legal.ts DATA_PROMISE).
DATA_PROMISE = "We never sell your data or use it for ads."


def contact_email(contact: str = "") -> str:
    return contact or DEFAULT_CONTACT


def _who(contact: str) -> str:
    c = escape(contact_email(contact))
    return f'<a href="mailto:{c}">{c}</a>'


def _page(slug: str, title: str, body: str, contact: str) -> str:
    nav = "".join(f'<a href="/app/{s}"{" aria-current=page" if s == slug else ""}>{escape(lbl)}</a>'
                     for s, (_, lbl) in DOCS.items())
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>rabbt · {escape(title)}</title>
<style>:root{{color-scheme:light dark;--bg:#f6f2ea;--fg:#1b1d1c;--muted:#5d625f;--brand:#1f4a33;--accent:#2f7d5b;--line:#ddd6c8}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151716;--fg:#ecebe6;--muted:#a3a8a4;--brand:#9fd3b6;--accent:#7fc9a3;--line:#2c302e}}}}
body{{margin:0;font:17px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--bg);color:var(--fg)}}
main{{max-width:65ch;margin:0 auto;padding:32px 20px 72px}}h1{{font:600 1.9rem/1.2 Georgia,serif;color:var(--brand);margin:0 0 8px}}
h2{{font-size:1.2rem;line-height:1.3;margin:36px 0 8px}}.sub{{color:var(--muted);margin:0 0 20px;font-size:1rem}}p,ul{{margin:12px 0}}
nav{{font-size:1rem;margin:0 0 24px;color:var(--muted);display:flex;flex-wrap:wrap;gap:4px 16px}}nav a{{padding:10px 0}}nav a[aria-current]{{font-weight:600;text-decoration:none}}
li{{margin:8px 0}}a{{color:var(--accent)}}.box{{border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin:18px 0}}
@media print{{nav{{display:none}}body{{background:#fff;color:#000}}a{{color:#000}}}}</style></head><body><main>
<nav aria-label="rabbt policies">{nav}</nav>
<h1>{escape(title)}</h1><p class=sub>rabbt training coach, operated by {OPERATOR}.<br>Updated {UPDATED}, version {VERSION}.</p>
{body.replace("{CONTACT}", _who(contact))}
<footer class=sub style="margin-top:40px;border-top:1px solid var(--line);padding-top:16px">{escape(DATA_PROMISE)}</footer>
</main></body></html>"""


# ------------------------------------------------------------------ privacy --
# Facts: webauth.py (Google sign-in; sessions stored as sha256; cookie httponly/secure/lax;
# config.app_session_ttl_seconds 90 days), passkeys.py, access.py (invites), garminlogin.py +
# tokens.py (password used once, Fernet token), oura.py/sources.py (display-only), gcalendar.py
# (read-only; coach sees busy hours + travel windows with title), tpsync.py, geo.round2 (~1 km),
# weather.py (Open-Meteo), explore.py (RunSignup), clubdir.py (RabbitBot, Nominatim),
# partners.py (labelled "Sponsored partner"; anonymous counts, owner only), agent.py (Anthropic
# API, web_search tool), usage.py, webpush.py, sharelinks.py (HR only when included; never
# location), appstore.py (Fernet per-user docs), infra/write-config.sh (us-central1),
# infra/cloudshell/10-backups.sh (14 days), 14-offsite-backups.sh (30 days / 12 months).
PRIVACY = """
<p>rabbt is a small, private training app used by invited athletes and their coaches, run by """ + OPERATOR + """ ("we"). This policy explains what rabbt collects, why, who sees it, how long it's kept and the choices you have.</p>
<div class=box><b>The short version.</b> rabbt uses your training data to coach you. It doesn't sell your data, show ads or use ad trackers. Oura, WHOOP and Apple Watch data are never sent to the AI coach. You can download your data or delete your account any time in <b>Me &rarr; Privacy &amp; legal</b>.</div>

<h2>What rabbt collects</h2>
<ul>
<li><b>How you sign in</b>: with Google (name, email and profile picture) or with a passkey. Only invited people can use rabbt.</li>
<li><b>Passkeys</b>: rabbt stores only each passkey's public key and a usage counter. The private key and your fingerprint or face data never leave your device or password manager.</li>
<li><b>Joining with an invite link</b>: your first name, and an email address that is used only to contact you about your account. It isn't verified, isn't shown to other athletes and isn't used for marketing.</li>
<li><b>Garmin Connect</b> (when you connect it): workouts, heart rate, sleep, HRV, readiness and similar training data, and the planned workouts rabbt sends to your watch. Your Garmin password is passed to Garmin once to sign in and is never stored; rabbt keeps only Garmin's sign-in token, encrypted.</li>
<li><b>Oura</b> (when you connect it): readiness, sleep, heart rate variability, resting heart rate and daily activity summaries. Workouts Oura recorded that Garmin didn't (time, sport, distance, calories) are shown in your day and, if you share workouts, as a workout card for friends; they don't count toward streaks, stats or plan matching, which use Garmin workouts only, and they are deleted when you disconnect Oura.</li>
<li><b>WHOOP</b> (when you connect it): workouts WHOOP recorded that Garmin didn't (time, sport, distance). They are shown in your day and, if you share workouts, as a workout card for friends; strain, heart rate and calories are never shared. Like Oura's, they don't count toward streaks, stats or plan matching, and they are deleted when you disconnect WHOOP.</li>
<li><b>Apple Watch</b> (when you set it up): rabbt can't read Apple Health itself. An iPhone Shortcut you build sends your recent workouts to rabbt with a personal import key, and rabbt keeps only each workout's sport, start time, duration and distance; heart rate, calories and anything else the Shortcut sends are thrown away. These workouts are shown in your day and, if you share workouts, as a workout card for friends; like Oura's, they don't count toward streaks, stats or plan matching. rabbt stores only a one-way hash of your import key. Turning Apple Watch off revokes the key, and you can choose to delete the imported workouts too.</li>
<li><b>Google Calendar</b> (when you connect it, read-only): event times, used to spot busy days and travel.</li>
<li><b>TrainingPeaks</b> (when you connect it): rabbt reads the planned workouts on your TrainingPeaks calendar (title, sport, duration, distance, description, coach notes and structure) from 2 weeks back to 6 weeks ahead. You connect by pasting your TrainingPeaks session value; rabbt stores it encrypted, never logs it and never asks for your TrainingPeaks password. rabbt writes to TrainingPeaks only when you choose rabbt as your plan (it adds, updates and deletes the planned workouts it created for your next 14 days and never changes or deletes ones it didn't create) or when you move a TrainingPeaks workout in rabbt. Completed workouts are not imported from TrainingPeaks; they come from Garmin only.</li>
<li><b>What you enter</b>: your profile and training answers, goals, races, gear, photo, plan files you upload, chats and coach messages.</li>
<li><b>Health-related entries</b>: workout feedback (effort, how it felt), niggles and pain notes, and fueling logs. rabbt treats these, and your heart rate, sleep and recovery data, as sensitive health information.</li>
<li><b>Social content</b>: posts, comments, cheers, direct messages, clubs, groups and events, your training-buddy profile (if you turn it on) and links you share.</li>
<li><b>Finding friends</b>: your @handle, and a phone number if you choose to add one (it isn't verified, is never shown to anyone and is only used so people who have it can find you). When you check your contacts, the emails and phone numbers you pick are compared with people on rabbt and then thrown away: rabbt doesn't store or log them, and never contacts anyone in them. In Me &rarr; Privacy &amp; legal &rarr; How friends find you, you choose whether people can find you by name, email or phone.</li>
<li><b>Location</b>: the home city or zip you give and, only if you tap "Use my location", a position rounded to about 1 km. <b>Routes</b>: when you share a workout with friends, rabbt keeps its GPS line on that post so friends can see it on the Feed map. The first and last 400 m are cut off (you can choose 200 m or 800 m), routes that start near a spot you hide are only shown to you, and "Keep maps private" in Community settings hides your lines from everyone else. Routes are never sold, used for ads or sent to the AI coach.</li>
<li><b>Notifications</b>: if you allow them, your browser's push subscription for each device.</li>
<li><b>Usage counts</b> (below) and basic server logs needed to run and secure the app.</li>
</ul>

<h2>How it's used</h2>
<ul>
<li>To build and adjust your training plan, show your stats and progress, and power the AI coach.</li>
<li>To run the social features you choose (feed, messages, clubs, buddies, sharing) and keep them safe (blocking, reports, limits on abuse).</li>
<li>Chats with the AI coach are processed by Anthropic's API. <b>Oura, WHOOP and Apple Watch data are never sent to the AI coach</b>: they are only shown in the app (and Oura's is used by fixed rules, for example easing your plan after poor recovery). From your calendar, the coach sees only busy hours and travel windows.</li>
<li>Coaches you invite can see your plan, races, stats and anything you share with them. Your chats with the AI coach stay private unless you turn on sharing.</li>
<li>rabbt does not sell your data, share it for targeted advertising or show ads. To work, it sends the minimum needed to a few services: race searches to RunSignup, a rounded location (about 1 km) to OpenStreetMap for your city and nearby places, and your city to Open-Meteo for weather. Nothing else about you is shared.</li>
<li><b>Clubs &amp; leagues directory</b>: Community lists run clubs, group rides, tri clubs, swims and adult leagues built from the public web. rabbt searches the web with only a city and state, then its crawler, RabbitBot, reads the public pages it finds (it obeys robots.txt, goes slowly, and never reads social networks like Facebook, Instagram, Strava or Meetup, which are only linked). The directory holds public facts about groups (name, schedule, meeting place, cost, link), never anything about you or other athletes. Suggestions and "outdated" reports you send are stored with your account to limit abuse.</li>
<li><b>Partners</b>: a few local groups are rabbt partners and can appear, always labelled "Partner" or "Sponsored partner", to people in their area. Partners never receive your data; only rabbt's owner sees anonymous totals (views and taps).</li>
<li><b>Usage counts</b>: to see which parts of the app help, rabbt counts a few anonymous actions on its own server (no outside analytics): opening the app, which tab you view, taps on the Up next, weekly ring, race grade, reward and quick-action cards, setup steps reached, joining by invite, sharing, cheering, RSVPs and opening a notification. Only fixed names are counted (never free text, health or training data, or location), and only as daily totals. To count daily, weekly and monthly users, your account is turned into a code that changes every day and can't be linked across days; your account itself keeps just two dates (first and last day you used the app) for the weekly and returning-user numbers. No individual event is stored. Only the app's owner sees the totals. Turn on "Don't count my usage" in Settings (or Do Not Track / Global Privacy Control in your browser) and nothing is counted.</li>
</ul>

<h2>AI processing</h2>
<p>rabbt's coach uses Anthropic's Claude API. It receives your messages, your training profile and plan, relevant Garmin numbers, your own notes and the calendar summary above, and it can search the web. It never receives Oura, WHOOP or Apple Watch data or any password, sign-in token or import key. Anthropic's <a href="https://www.anthropic.com/legal/commercial-terms" rel="noopener">commercial terms</a> don't allow it to train its models on what rabbt sends through the API. AI replies can be wrong; see the <a href="/app/terms">terms</a>.</p>

<h2>Who else sees your data</h2>
<ul>
<li><b>Service providers</b> that run rabbt: Google Cloud (hosting in the US and encrypted backups), Anthropic (AI coach) and your browser's push service (Apple, Google or Mozilla) to deliver notifications.</li>
<li><b>Apps you connect</b>: Garmin, Oura, WHOOP, Google and TrainingPeaks, under their own terms. Apple Watch workouts come from your own iPhone Shortcut; nothing is sent to Apple.</li>
<li><b>Other rabbt users</b>, only as your settings allow: people you follow or message, club and group members, training buddies, and anyone you send a share link to. Share links never include your location, and include heart rate only if you choose.</li>
<li><b>Legal reasons</b>: if the law requires it, or to protect someone's safety.</li>
</ul>

<h2>Cookies and storage</h2>
<p>rabbt uses one essential sign-in cookie (HTTP-only and secure, kept up to 90 days or until you sign out), a first-party cookie kept for 7 days that remembers which club page or invite link brought you (only the club's short name or the word "invite", used to count how people find rabbt), and your browser's local storage for things like theme, units, drafts and dismissed tips. There are no advertising or third-party tracking cookies, so there's nothing to opt out of.</p>

<h2>How long it's kept</h2>
<ul>
<li>Your data is kept until you delete it or delete your account.</li>
<li>Disconnecting an app deletes its stored tokens right away (and Oura or WHOOP workouts); rabbt stops reading from it.</li>
<li>When you delete your account, your data is deleted from the live server right away. Encrypted backups expire on their own schedule: server snapshots after 14 days, off-server daily copies after 30 days and monthly copies after 12 months.</li>
<li>Messages you sent stay in the other people's conversations, without your name or photo.</li>
</ul>

<h2>Security</h2>
<p>Each person's data is stored in separate files encrypted at rest. Encryption keys and service secrets are kept in Google Secret Manager. Sign-in sessions, share links, calendar links and Apple Watch import keys are stored only as one-way hashes. See <a href="/app/security">How rabbt keeps your data safe</a>.</p>

<h2>Your rights and choices</h2>
<ul>
<li><b>Download your data</b> or <b>delete your account</b> any time in Me &rarr; Privacy &amp; legal.</li>
<li>Correct your information in your profile and settings, turn off sharing, buddies and usage counting in Settings, and disconnect Garmin, Oura, WHOOP, Google Calendar, TrainingPeaks or Apple Watch at any time in Me &rarr; Connected apps; rabbt stops reading from them and deletes the stored tokens.</li>
<li>Depending on where you live (for example under the Colorado Privacy Act, California's CCPA/CPRA or the GDPR), you may have the right to access, correct, delete or port your data, to object to or restrict processing, and to withdraw consent. rabbt doesn't sell personal data, use it for targeted advertising or make decisions with legal effects about you. For anything the app doesn't do for you, contact {CONTACT}; we reply within 45 days (30 where the GDPR applies), and you can appeal a decision by replying to it.</li>
</ul>

<h2>Health information</h2>
<p>rabbt is a training tool, not a medical device, and doesn't diagnose or treat anything. You give explicit consent to rabbt processing your health and fitness data when you start using it, and you can withdraw it by deleting your account. Sharing your workouts with friends is a separate choice you can turn on or off any time. The <a href="/app/health-data">consumer health data privacy policy</a> covers this in detail, including your rights under Washington's My Health My Data Act and similar laws in Nevada and Connecticut.</p>

<h2>If there's a breach</h2>
<p>If someone gets into rabbt's systems and your health or fitness data is exposed, we will tell you by email and in the app without unreasonable delay, and no later than 60 days after we find out. We'll say what happened, what data was involved, what we're doing about it and what you can do to protect yourself. We will also notify the Federal Trade Commission, and the media where the law requires it (for example when 500 or more people in one state are affected), as the FTC's Health Breach Notification Rule requires.</p>

<h2>Children</h2>
<p>rabbt is not for anyone under 16. If you believe someone under 16 has an account, contact {CONTACT} and it will be deleted.</p>

<h2>Where data is processed</h2>
<p>rabbt runs in the United States. If you use it from elsewhere, your data is transferred to and processed in the US.</p>

<h2>Changes</h2>
<p>When this policy changes in a meaningful way, the date and version above change and the app asks you to review it again.</p>

<h2>Contact</h2><p>Questions: {CONTACT}.</p>
"""

# -------------------------------------------------------------------- terms --
TERMS = """
<p>These terms are an agreement between you and """ + OPERATOR + """, who runs rabbt. By using rabbt you agree to them and to the <a href="/app/privacy">privacy policy</a>.</p>
<h2>Who can use rabbt</h2>
<p>You must be 16 or older and invited. Use rabbt only with your own accounts and data, and keep your sign-in secure. You're responsible for what happens on your account.</p>
<h2>What rabbt is</h2>
<p>rabbt is a personal training tool offered free to invited users, as is, without warranties. It may change or stop at any time.</p>
<h2>Not medical advice</h2>
<p>Training plans, AI coach replies, readiness and recovery insights, weather changes and injury or fueling tips are general guidance, not medical advice. Check with a doctor before starting or changing training, and stop if you feel unwell or injured. You are responsible for how you train.</p>
<h2>Training safely</h2>
<p>Endurance training and sport carry real risks, including injury, illness and accidents. You choose when, where and how hard to train, and you take part at your own risk. Stop and get help if something feels wrong.</p>
<h2>Your health data</h2>
<p>rabbt uses your training and health data only to coach you and run the features you choose. We never sell your data or use it for ads. Sharing workouts with friends is your choice, and you can download or delete everything at any time. Details are in the <a href="/app/privacy">privacy policy</a> and the <a href="/app/health-data">consumer health data privacy policy</a>. If there's ever a data breach that affects you, we'll tell you within 60 days, as described in the privacy policy.</p>
<h2>AI replies</h2>
<p>rabbt's coach uses AI and can be wrong or incomplete. Use your own judgment and double-check anything important.</p>
<h2>Your content</h2>
<p>You own what you post and upload. You let rabbt store, process and show it only as needed to run the features you use (for example, showing a post to the people you shared it with). You can delete it any time. Only post things you have the right to share.</p>
<h2>Community</h2>
<p>Follow the <a href="/app/guidelines">community guidelines</a>. You can block and report people; rabbt may remove content or suspend accounts that break the rules.</p>
<h2>Your account</h2>
<ul>
<li>Don't misuse the service: no trying to access other people's data or accounts, breaking security, scraping, or overloading it.</li>
<li>Don't use rabbt for anything unlawful or for unwanted advertising.</li>
</ul>
<h2>Connected services</h2>
<p>Garmin, Oura, WHOOP, Google, TrainingPeaks and Anthropic have their own terms, which also apply when you connect them. rabbt uses their data only as described in the <a href="/app/privacy">privacy policy</a> and isn't responsible for their availability or accuracy.</p>
<h2>Partners</h2>
<p>Some local groups appear labelled "Partner" or "Sponsored partner". They're promoted by rabbt; rabbt doesn't run their events, so check details with them directly.</p>
<h2>Ending your account</h2>
<p>You can delete your account any time in Me &rarr; Privacy &amp; legal. rabbt may suspend or close accounts that break these terms or put others at risk.</p>
<h2>Liability</h2>
<p>To the extent the law allows, rabbt's operator isn't liable for injuries, lost data or other losses from using the app. Nothing here limits rights you have by law that can't be waived.</p>
<h2>Governing law</h2>
<p>These terms are governed by the laws of the State of """ + GOVERNING + """, without regard to conflict-of-law rules.</p>
<h2>Changes</h2>
<p>When these terms change in a meaningful way, the date and version above change and the app asks you to review them again.</p>
<h2>Contact</h2><p>Questions: {CONTACT}.</p>
"""

# ----------------------------------------------------------------- security --
# Facts: appstore.py (Fernet per user), infra/setup.sh + 8-oura.sh (Secret Manager),
# webauth/sharelinks/calsub _hash (sha256), garminlogin.py, tpsync.py, 13-autodeploy.sh
# (deploy-only service account can't read secrets), 10-backups.sh, 14-offsite-backups.sh.
SECURITY = """
<p>Here's how rabbt protects your data, in plain words.</p>
<ul>
<li><b>Encrypted at rest.</b> Each person's data lives in its own encrypted files (Fernet: AES with an integrity check). Without the key, the files are unreadable.</li>
<li><b>Keys kept apart.</b> Encryption keys and service secrets are kept in Google Secret Manager, separate from the data and the backups.</li>
<li><b>Encrypted in transit.</b> The sign-in cookie only travels over HTTPS and can't be read by scripts.</li>
<li><b>Passwords never stored.</b> You sign in with Google or a passkey. Your Garmin password goes to Garmin once and isn't kept, only an encrypted sign-in token is. rabbt never asks for your TrainingPeaks password.</li>
<li><b>Hashed links and sessions.</b> Sign-in sessions, share links and calendar links are stored only as one-way hashes, and you can turn any link off.</li>
<li><b>Least access.</b> Connected apps are read-only unless you ask rabbt to write (like sending a workout to your watch). The automatic deploy system can update the app but can't read secrets.</li>
<li><b>Backups.</b> Encrypted copies protect against a server failure: server snapshots for 14 days, and off-server copies for 30 days (daily) and 12 months (monthly). Backups hold only encrypted data.</li>
<li><b>Private by default.</b> Nothing is shared until you say yes, routes on shared workouts are trimmed so your home never shows, heart rate isn't shared unless you choose, and Oura and WHOOP data never goes to the AI coach.</li>
<li><b>Your controls.</b> Download your data or delete your account in Me &rarr; Privacy &amp; legal, and disconnect apps in Me &rarr; Connected apps.</li>
</ul>
<h2>If there's a breach</h2>
<p>If your health or fitness data is ever exposed, rabbt will tell you by email and in the app within 60 days of finding out (sooner whenever possible), explain what happened and what to do, and notify the FTC as its Health Breach Notification Rule requires.</p>
<p>Found a security problem? Please email {CONTACT} and don't share it publicly until it's fixed.</p>
"""

# --------------------------------------------------------------- guidelines --
GUIDELINES = """
<p>rabbt is for cheering each other on. A few rules keep it that way:</p>
<ul>
<li><b>Be kind.</b> No harassment, bullying, hate, threats or body shaming. Every pace counts.</li>
<li><b>Be real.</b> Don't impersonate anyone or fake workouts or results.</li>
<li><b>Respect privacy.</b> Don't share other people's private information, locations or messages without permission.</li>
<li><b>No spam.</b> No unwanted ads, chain messages or scams. Clubs can share their own events.</li>
<li><b>Keep it safe and legal.</b> No illegal content, and don't push others toward dangerous training, extreme dieting or ignoring injuries.</li>
</ul>
<p>See something wrong? Block the person and use Report. Reports go to rabbt's owner, who may remove content or suspend accounts. Questions: {CONTACT}.</p>
"""

# ------------------------------------------------------------- health data --
# Washington My Health My Data Act (RCW 19.373), Nevada SB 370, Connecticut (CTDPA health data).
# Facts: same sources as PRIVACY above; consent.py records the collection consent ("health") and
# the separate sharing consent ("share", wired to community share_workouts).
HEALTH_DATA = """
<p>This policy explains how rabbt handles <b>consumer health data</b>: information about your body, health and fitness. It sits alongside the main <a href="/app/privacy">privacy policy</a> and is written for Washington's My Health My Data Act and similar laws in Nevada and Connecticut, but it applies to everyone who uses rabbt.</p>
<div class=box><b>The short version.</b> We collect health and fitness data only to coach you and run the features you turn on. We never sell it and never use it for ads. Sharing it with other people only happens when you choose to. You can see, download or delete all of it at any time.</div>

<h2>What consumer health data we collect</h2>
<ul>
<li>Workouts: sport, time, distance, pace, power, heart rate and splits.</li>
<li>Sleep, readiness, heart rate variability and resting heart rate.</li>
<li>How workouts felt, effort ratings and notes you write.</li>
<li>Niggles, pain and injury notes, and the dates you turn on sick mode.</li>
<li>Fueling notes and food preferences you choose to give.</li>
<li>Body details you give, like age, height and weight.</li>
<li>Your home city, used to suggest local clubs and weather. Routes are kept only on workouts you share, trimmed at the start and finish.</li>
</ul>

<h2>Where it comes from</h2>
<p>From you, and from apps you connect: Garmin, Oura, WHOOP and Apple Health (through a Shortcut you set up). Each app sends data only after you connect it, and stops when you disconnect.</p>

<h2>Why we use it</h2>
<ul>
<li>To build and adjust your training plan, including easing it when you're tired, sick or travelling.</li>
<li>To show your stats, progress and workout details.</li>
<li>To answer your questions in the coaching chat.</li>
<li>To show workouts to friends and groups, only if you turn sharing on.</li>
</ul>
<p>We don't use it for advertising, and we don't make decisions with legal effects about you.</p>

<h2>Who we share it with</h2>
<ul>
<li><b>Service providers</b> that run rabbt for us under contract: Google Cloud (hosting and encrypted backups), Anthropic (coaching replies) and push notification services (Apple, Google, Mozilla). They may use it only to provide their service to rabbt.</li>
<li><b>Other rabbt users</b>, only when you choose: workouts you share with friends, groups or clubs, and anything you post.</li>
<li><b>Legal reasons</b>: when the law requires it, or to protect someone's safety.</li>
</ul>
<p><b>We never sell consumer health data</b>, and we never share it with data brokers or advertisers.</p>

<h2>Your consent</h2>
<p>We ask for your consent before collecting health data beyond what the app needs to work, and separately before sharing any of it with other people. You give these consents on the "Before you start" screen and when you choose to share workouts. You can withdraw either one at any time: turn off sharing in Me, disconnect apps in Me &rarr; Connected apps, or delete your account.</p>

<h2>Your rights</h2>
<ul>
<li><b>See your data</b> and get a copy: Me &rarr; Privacy &amp; legal &rarr; Download my data.</li>
<li><b>Delete your data</b>: Me &rarr; Privacy &amp; legal &rarr; Delete my account. This also removes it from the services that run rabbt for us; backups expire on the schedule in the privacy policy.</li>
<li><b>Withdraw consent</b> at any time, as described above.</li>
<li><b>Know who has it</b>: ask us for the list of service providers and other parties your health data was shared with.</li>
<li><b>Appeal</b>: if we turn down a request, reply to our answer and we'll review it. If you're still not satisfied, you can contact your state attorney general (in Washington, the Washington State Attorney General's Office).</li>
</ul>
<p>We answer requests within 45 days. Email {CONTACT} for anything the app doesn't do for you.</p>

<h2>How we protect it</h2>
<p>Your data is encrypted at rest, kept in separate files per person, and only the people who run rabbt can access the systems that hold it. See <a href="/app/security">How rabbt keeps your data safe</a>. If there's ever a breach, we'll tell you within 60 days, as described in the privacy policy.</p>

<h2>Contact</h2>
<p>rabbt is operated by """ + OPERATOR + """ in """ + GOVERNING + """ (to become rabbt LLC). Questions or requests: {CONTACT}.</p>
"""

ABOUT = """
<p><b>RabbitBot</b> is the web crawler of rabbt, a small private training app. It builds a directory of local run clubs, group rides, triathlon clubs, masters swims and adult sports leagues so athletes can find people to train with.</p>
<h2>How it behaves</h2>
<ul>
<li>User agent: <code>RabbitBot/1.0</code>. It obeys <code>robots.txt</code> (use <code>User-agent: RabbitBot</code>).</li>
<li>At most one request per second per site, about 25 pages per city per month, HTML pages only.</li>
<li>It reads only public pages that web search links to a city's clubs and leagues, and keeps public facts about groups: name, schedule, meeting place, cost and a link back to your page.</li>
<li>It never logs in, submits forms or reads social networks.</li>
</ul>
<h2>Opt out or correct something</h2>
<p>Disallow RabbitBot in robots.txt, or contact {CONTACT} and we'll remove or fix a listing.</p>
"""

_BODIES = {"privacy": PRIVACY, "terms": TERMS, "security": SECURITY, "guidelines": GUIDELINES,
           "health-data": HEALTH_DATA}


def page(slug: str, contact: str = "") -> str:
    return _page(slug, DOCS[slug][0], _BODIES[slug], contact)


def body_html(slug: str, contact: str = "") -> str:
    """A document's body (trusted static HTML) for the in-app reader."""
    return _BODIES[slug].replace("{CONTACT}", _who(contact))


def about(contact: str = "") -> str:
    return _page("about", "RabbitBot", ABOUT, contact)


def privacy(contact: str = "") -> str:
    return page("privacy", contact)


def terms(contact: str = "") -> str:
    return page("terms", contact)


def security(contact: str = "") -> str:
    return page("security", contact)


def guidelines(contact: str = "") -> str:
    return page("guidelines", contact)


def health_data(contact: str = "") -> str:
    return page("health-data", contact)


# Appended inside the <footer> of public share pages (share.py, sharelinks.py, racepeople.py).
FOOTER = ('<br>' + DATA_PROMISE + '<br><a href="/app/privacy">Privacy</a> · <a href="/app/terms">Terms</a> · '
          '<a href="/app/health-data">Health data</a> · <a href="/app/security">Data &amp; security</a>')


__all__ = ["VERSION", "UPDATED", "OPERATOR", "DOCS", "FOOTER", "DATA_PROMISE", "contact_email", "page", "body_html",
           "about", "privacy", "terms", "security", "guidelines", "health_data"]
