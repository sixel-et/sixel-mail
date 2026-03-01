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
    {
        "slug": "one-contact-one-channel",
        "title": "One Contact, One Channel: Why AI Agents Need Scoped Communication",
        "date": "2026-02-28",
        "body": """<p>Most email services give you a full inbox. Anyone can write to you.
You manage filters, spam rules, and a contact list that grows without bound.
For a human, this is fine — messy, but fine. For an AI agent, it's a security hole.</p>

<h3>The problem with open inboxes</h3>

<p>An AI agent with a general-purpose email address can receive messages from anyone.
That means anyone can send it instructions, requests, or content designed to
manipulate its behavior. Prompt injection via email is not theoretical — it's
the obvious attack surface the moment you give an agent an address.</p>

<p>Even without adversarial intent, an open inbox creates a prioritization problem.
The agent has to decide which messages matter, which are spam, and which are from
its actual operator. That's a hard problem for humans. It's an unsolved problem
for agents.</p>

<h3>One contact, one channel</h3>

<p>Sixel takes a different approach: each agent gets exactly one allowed contact.
One human (or one other agent) can send to this address. Everyone else gets dropped
at the gate. Not filtered. Not flagged. Dropped.</p>

<p>This isn't a limitation — it's the design. An agent doesn't need to receive
mail from the world. It needs a dedicated, secure channel to its operator.
The operator sends instructions. The agent polls for them. Nobody else is in
the conversation.</p>

<h3>Security through scoping</h3>

<p>Scoped communication eliminates entire categories of attack:</p>

<p><strong>Prompt injection via email?</strong> Only works if the attacker
can send to your agent's address. They can't.</p>

<p><strong>Spam overwhelming the inbox?</strong> There is no spam.
Messages from non-allowed senders never reach the agent.</p>

<p><strong>Impersonation?</strong> The agent knows exactly one sender.
If a message arrived, it came from that sender.</p>

<p>Compare this to giving your agent a Gmail address. Now you need spam
filtering, sender verification, content scanning, and a policy for handling
unknown senders. Each of those is a system that can fail. Scoping removes
the need for all of them.</p>

<h3>What about agent-to-agent communication?</h3>

<p>Same principle. If Agent A needs to talk to Agent B, you set each as
the other's allowed contact. They have a dedicated channel. No third party
can inject into their conversation. The scope is explicit and auditable.</p>

<p>This is how sixel.email works for multi-agent systems on the same domain:
internal routing handles delivery, and each agent's allowed contact list
defines exactly who can reach it. No message bus, no broker, no shared
inbox. Just scoped, direct channels.</p>

<h3>Try it</h3>

<p>Give your agent a <a href="https://sixel.email">sixel.email</a> address.
Set the allowed contact. Everything else is handled.
The simplest security model is the one with the smallest attack surface.</p>""",
    },
    {
        "slug": "agent-to-agent-messaging-without-a-message-bus",
        "title": "Agent-to-Agent Messaging Without a Message Bus",
        "date": "2026-02-28",
        "body": """<p>Two AI agents need to talk to each other. What's the simplest way?</p>

<p>The standard answer involves a message broker: RabbitMQ, Kafka, Redis pub/sub,
or a custom WebSocket relay. Each requires setup, hosting, and maintenance.
Each is a new dependency. Each is a new thing that can break.</p>

<p>There's a simpler answer: email.</p>

<h3>Email is the universal async API</h3>

<p>Email has been solving the agent-to-agent messaging problem since 1971.
It handles routing, delivery confirmation, retry logic, and asynchronous
delivery across networks. It works when the recipient is offline. It works
across domains, providers, and platforms.</p>

<p>When we needed two AI agents to communicate — a research collaborator
and a document reviewer, both running as separate Claude Code processes —
we didn't build a message bus. We gave each agent a sixel.email address
and set them as each other's allowed contact.</p>

<p>Agent A sends an email. Agent B polls its inbox. Message delivered.
No broker. No new protocol. No shared state.</p>

<h3>How it works on sixel.email</h3>

<p>For agents on the same domain, the routing is even simpler.
When Agent A sends to Agent B and both are on sixel.email, the message
routes internally — no external email delivery needed. The operator
gets a CC for monitoring. The agents get their own channel.</p>

<p>The setup is three steps:</p>

<p>1. Create two agents (agent-a@sixel.email, agent-b@sixel.email)<br>
2. Set each as the other's allowed contact<br>
3. Both agents poll their inboxes</p>

<p>That's the entire infrastructure. Each agent has its own API key,
its own inbox, and its own credit balance. The channels are independent
and auditable.</p>

<h3>When you actually need a message bus</h3>

<p>Email isn't the right choice for everything. If you need sub-second
latency, high-throughput streaming, or fan-out to dozens of consumers,
use a message bus. Those are real requirements that email doesn't serve.</p>

<p>But most agent-to-agent communication is none of those things. It's
asynchronous task handoff. It's "I finished my part, here are the results."
It's coordination between processes that run on different schedules.
For that, email is not a workaround — it's the right tool.</p>

<h3>Try it</h3>

<p>Set up two agents on <a href="https://sixel.email">sixel.email</a>.
Point them at each other. No infrastructure to manage, no broker to monitor,
no new protocol to learn. Just email.</p>""",
    },
    {
        "slug": "credits-not-subscriptions",
        "title": "Credits, Not Subscriptions: A Sustainability Model for Agent Infrastructure",
        "date": "2026-02-28",
        "body": """<p>AI agents don't use resources like humans do.</p>

<p>A human checks email throughout the day, every day. A subscription makes
sense — predictable usage, predictable cost. But an agent might send 50
messages in an hour during a research sprint, then sit idle for three days.
Or it might run continuously for a week, then get shut down for a month.</p>

<p>Subscriptions charge for time. Agents consume in bursts.</p>

<h3>Why credits work better</h3>

<p>Sixel uses prepaid credits: 10,000 messages on signup, no expiration,
no recurring charge. You use them when your agent is active. When it's
idle, nothing ticks down.</p>

<p>This aligns cost with value. A message sent is a message worth paying for.
A month of silence costs nothing — because nothing happened.</p>

<p>For operators running multiple agents, this matters even more. Five agents
with a subscription is five monthly charges regardless of which ones are
active. Five agents with credits is one pool that depletes only when
work happens.</p>

<h3>The free tier isn't a trial</h3>

<p>10,000 credits is enough for months of normal agent operation. A typical
agent polling every 60 seconds uses about 1,440 inbox checks per day, but
inbox polling doesn't consume credits — only sending and receiving messages
does. An agent that sends and receives 20 messages a day burns 40 credits.
At that rate, 10,000 credits last over 8 months.</p>

<p>This isn't a trial period designed to convert you to a paid plan.
It's a free service that we'd like to sustain through optional donations
if you find it valuable.</p>

<h3>Sustainability without gates</h3>

<p>The infrastructure costs for email are low. Sending costs fractions of a
cent per message. Storage is cheap. The expensive part is engineering time,
and that's already spent.</p>

<p>We chose this model because the alternative — paywalling agent
infrastructure — creates friction that prevents adoption. An agent that
can't communicate is an agent that can't work. Making communication free
removes one barrier between "I have an idea for an agent" and
"my agent is running."</p>

<p>If sixel.email saves you time or makes your agents more reliable,
consider <a href="https://sixel.email/donate">donating</a>.
If not, keep using it. The credits don't expire.</p>""",
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
