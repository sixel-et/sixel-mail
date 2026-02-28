from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

# Blog posts as simple inline content for now.
# When we have more posts, we can move to markdown files in a /blog directory.

POSTS = [
    {
        "slug": "the-silent-crash-problem",
        "title": "The Silent Crash Problem: Why Your AI Agent Needs a Dead Man's Switch",
        "date": "2026-02-28",
        "body": """<p>My agent crashed for six hours and I had no idea.</p>

<p>I was running a Claude Code instance as a persistent research collaborator.
It had tasks queued, context loaded, work in progress. At some point during the night,
the process died. No error email. No alert. No signal of any kind. I found out the next
morning when I checked the tmux pane and saw a blank prompt.</p>

<p>Six hours of availability, gone. Any inbound messages during that window — dropped.
Any scheduled work — missed. The failure mode wasn't the crash itself. Crashes happen.
The failure mode was <strong>silence</strong>.</p>

<h3>The infrastructure gap</h3>

<p>If you're running a web service, you have uptime monitoring. Pingdom, UptimeRobot,
a simple cron job that curls your health endpoint. The tooling exists because the problem
is well-understood: services go down, and you need to know when they do.</p>

<p>AI agents don't have this. An agent running in a terminal, in a Docker container,
in a cloud VM — when it dies, it just stops. There's no health endpoint to ping.
There's no process manager that understands "this agent should be doing work."
The agent is supposed to be autonomous, which means nobody is watching it by definition.</p>

<h3>The dead man's switch</h3>

<p>The solution turned out to be embarrassingly simple.</p>

<p>My agent was already polling for messages — checking an inbox endpoint every 60 seconds
to see if I'd sent it anything. That polling <em>is</em> a heartbeat. If the agent is alive,
it polls. If it's dead, it stops polling. The server already knows the difference.</p>

<p>So I added a timer. If the agent hasn't polled in 10 minutes, send me an email:
"Your agent hasn't checked in. Last seen: [timestamp]."</p>

<p>That's it. No extra infrastructure. No separate monitoring service.
The communication channel itself became the liveness monitor.
A dead man's switch — if the agent stops holding down the button, the alarm goes off.</p>

<h3>Why this matters more than you think</h3>

<p>Silent failure is the default mode for AI agents. Every agent framework —
LangChain, CrewAI, AutoGPT, Claude Code — can crash without notification.
The more autonomous the agent, the longer the failure goes unnoticed,
because the whole point is that you're not watching it.</p>

<p>This isn't a monitoring problem you can solve with generic uptime tools.
The agent isn't a web service with a URL to ping. It's a process that should be
<em>doing things</em> — and the only reliable signal that it's doing things is
that it's communicating.</p>

<p>The communication channel is the natural place for the heartbeat.
Not bolted on. Built in.</p>

<h3>Try it</h3>

<p><a href="https://sixel.email">Sixel</a> gives your agent a private email address
with a built-in dead man's switch. Two endpoints, one API key, five lines in your
agent config. Free.</p>""",
    },
]


def _page_style():
    return """
    body {
        font-family: 'SF Mono', 'Menlo', 'Monaco', 'Courier New', monospace;
        max-width: 640px;
        margin: 60px auto;
        padding: 0 20px;
        line-height: 1.6;
        color: #1a1a1a;
        background: #fff;
    }
    h1 { font-size: 24px; margin-bottom: 4px; }
    h3 { font-size: 15px; margin-top: 28px; }
    .tagline { color: #666; margin-bottom: 40px; }
    .post-date { color: #999; font-size: 13px; }
    .post-list { list-style: none; padding: 0; }
    .post-list li { margin: 16px 0; }
    .post-list a { color: #1a1a1a; text-decoration: none; font-weight: bold; }
    .post-list a:hover { text-decoration: underline; }
    .footer { margin-top: 48px; color: #999; font-size: 13px; }
    .footer a { color: #666; }
    a { color: #1a73e8; }
    """


@router.get("/blog", response_class=HTMLResponse)
async def blog_index():
    post_items = ""
    for post in POSTS:
        post_items += (
            f'<li><span class="post-date">{post["date"]}</span> '
            f'<a href="/blog/{post["slug"]}">{post["title"]}</a></li>\n'
        )
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<title>Blog — sixel.email</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Updates and ideas from Sixel — private communication infrastructure for AI agents.">
<style>{_page_style()}</style>
</head>
<body>

<h1><a href="/" style="color:#1a1a1a;text-decoration:none;">sixel.email</a></h1>
<p class="tagline">Blog</p>

<ul class="post-list">
{post_items}
</ul>

<div class="footer">
    <p><a href="/">Home</a> &mdash;
    <a href="/best-practices">Best practices</a> &mdash;
    <a href="/donate">Donate</a> &mdash;
    Built by <a href="https://github.com/sixel-et">sixel-et</a></p>
</div>

</body></html>"""


@router.get("/blog/{slug}", response_class=HTMLResponse)
async def blog_post(slug: str):
    post = next((p for p in POSTS if p["slug"] == slug), None)
    if not post:
        return HTMLResponse(status_code=404, content="Post not found.")
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<title>{post["title"]} — sixel.email</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{post["title"]}">
<meta property="og:title" content="{post["title"]}">
<meta property="og:type" content="article">
<meta property="og:url" content="https://sixel.email/blog/{post["slug"]}">
<style>{_page_style()}</style>
</head>
<body>

<h1><a href="/" style="color:#1a1a1a;text-decoration:none;">sixel.email</a></h1>
<p class="tagline"><a href="/blog" style="color:#666;text-decoration:none;">Blog</a></p>

<h2 style="font-size:18px;border:none;padding:0;">{post["title"]}</h2>
<p class="post-date">{post["date"]}</p>

{post["body"]}

<div class="footer">
    <p><a href="/blog">&larr; All posts</a> &mdash;
    <a href="/">Home</a> &mdash;
    Built by <a href="https://github.com/sixel-et">sixel-et</a></p>
</div>

</body></html>"""
