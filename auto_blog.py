#!/usr/bin/env python3
"""
auto_blog.py — Probabilistic auto-blogger for taylor-riley.com

Decision logic (relative to the date in .github/last_post_date.txt):
  * < 7 days  -> do nothing
  * 7-13 days -> 20% chance to post today
  * >= 14 days -> must post today

When it posts, it asks the Anthropic API for an original article, inserts it
as the featured post in blog.html, demotes the previous featured post, bumps
sitemap.xml, and records today's date in the state file.

Designed to run in GitHub Actions. Reads ANTHROPIC_API_KEY from the env.
Commit/push and the notification email are handled by the workflow, gated on
the `posted` output this script writes to $GITHUB_OUTPUT.
"""

import argparse
import json
import os
import random
import re
import sys
from datetime import date, datetime

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
BLOG_HTML = os.path.join(REPO_ROOT, "blog.html")
SITEMAP = os.path.join(REPO_ROOT, "sitemap.xml")
STATE_FILE = os.path.join(REPO_ROOT, ".github", "last_post_date.txt")

TOPICS = [
    "tech",
    "the tax industry",
    "fatherhood",
    "living in Virginia",
    "something completely random and unexpected",
]

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")


# --------------------------------------------------------------------------- #
# State / gate
# --------------------------------------------------------------------------- #
def read_last_post_date():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            txt = f.read().strip()
        return datetime.strptime(txt, "%Y-%m-%d").date()
    except (FileNotFoundError, ValueError):
        return None


def write_last_post_date(d):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        f.write(d.strftime("%Y-%m-%d") + "\n")


def should_post(force=False):
    """Return (post: bool, reason: str)."""
    if force:
        return True, "forced via --force"

    last = read_last_post_date()
    today = date.today()
    if last is None:
        # No state yet: seed it and skip so we never post on first install.
        write_last_post_date(today)
        return False, "no state file found; seeded with today, skipping"

    days = (today - last).days
    if days < 7:
        return False, f"only {days} days since last post (<7); skipping"
    if days < 14:
        roll = random.random()
        if roll < 0.20:
            return True, f"{days} days since last post; 20% roll succeeded ({roll:.2f})"
        return False, f"{days} days since last post; 20% roll failed ({roll:.2f})"
    return True, f"{days} days since last post (>=14); posting is mandatory"


# --------------------------------------------------------------------------- #
# Content generation
# --------------------------------------------------------------------------- #
def existing_titles(html):
    return re.findall(r"<article class=\"blog-card[^\"]*\"[^>]*>.*?<h2>(.*?)</h2>", html, re.S)


def generate_post(html):
    """Call the Anthropic API and return a dict describing the new post."""
    import anthropic

    titles = existing_titles(html)
    avoid = "\n".join(f"- {t.strip()}" for t in titles)
    topic = random.choice(TOPICS)

    system = (
        "You are Taylor Riley, a technical leader with 15 years in tax technology. "
        "You currently lead engineering at Taxwell (TaxAct/Drake), build AI and MCP "
        "tooling, live in Virginia, and are a father. You write a personal blog in a "
        "sharp, candid, first-person voice with concrete detail, dry humor, and strong "
        "opinions. You avoid corporate filler and cliche."
    )

    prompt = f"""Write ONE brand-new, highly original blog post for my personal site.

Pick this theme for today's post: {topic}.

Do NOT repeat the themes or angles of these existing posts:
{avoid}

Return ONLY a JSON object (no markdown fences, no commentary) with exactly these keys:
{{
  "title": "a punchy, specific post title",
  "slug": "kebab-case-url-slug",
  "excerpt": "2-3 sentence teaser that makes someone want to read it",
  "reading_time": "e.g. '5 min read'",
  "body_html": "the article body as clean HTML using only <p>, <h3>, and optionally one <blockquote class=\\"blog-pullquote\\">...</blockquote> and/or one <aside class=\\"blog-counter\\"><strong>The Other Side:</strong> ...</aside>. 4-8 short sections. No <h1> or <h2>. No <html>/<head>/<body>. No inline styles.",
  "takeaways": ["3 to 4 short key-takeaway bullet strings"]
}}

Make it genuinely interesting and original — a real point of view, not generic advice."""

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(block.text for block in msg.content if block.type == "text").strip()

    # Strip accidental code fences.
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    post = json.loads(raw)
    post["topic"] = topic
    return post


def stub_post():
    """Offline placeholder used for --dry-run testing (no API call)."""
    return {
        "title": "Test Post: The Build Pipeline Works",
        "slug": "test-post-pipeline",
        "excerpt": "This is a dry-run placeholder used to verify the HTML insertion logic without calling the API.",
        "reading_time": "1 min read",
        "body_html": (
            "<p>If you are reading this on the live site, something went wrong "
            "and a dry-run post shipped. It should never happen in production.</p>"
            "<h3>Why this exists</h3>"
            "<p>It lets us verify the featured-post insertion, the demotion of the "
            "previous featured post, and the sitemap bump without spending API tokens.</p>"
        ),
        "takeaways": [
            "The gate logic ran.",
            "The HTML insertion ran.",
            "The sitemap was updated.",
        ],
        "topic": "dry-run",
    }


# --------------------------------------------------------------------------- #
# HTML assembly
# --------------------------------------------------------------------------- #
def build_article(post):
    date_label = datetime.now().strftime("%B %Y")
    slug = re.sub(r"[^a-z0-9-]", "", post["slug"].lower().replace(" ", "-"))
    takeaways = "\n".join(
        f"                            <li>{t}</li>" for t in post.get("takeaways", [])
    )
    takeaways_block = ""
    if takeaways:
        takeaways_block = f"""
                    <div class="blog-takeaways">
                        <h4>Key Takeaways</h4>
                        <ul>
{takeaways}
                        </ul>
                    </div>"""

    # Indent the model's body HTML to sit nicely inside .blog-body.
    body_lines = post["body_html"].strip().splitlines()
    body_html = "\n".join(
        ("                    " + line.strip()) if line.strip() else "" for line in body_lines
    )

    return f"""            <article class="blog-card blog-card-featured" id="{slug}">
                <div class="blog-progress" aria-hidden="true"><div class="blog-progress-bar"></div></div>
                <div class="blog-meta">
                    <span class="blog-date">{date_label}</span>
                    <span class="blog-reading">{post.get('reading_time', '5 min read')}</span>
                </div>
                <h2>{post['title']}</h2>
                <p class="blog-excerpt">
                    {post['excerpt'].strip()}
                </p>
                <div class="blog-body">
{body_html}{takeaways_block}
                </div>
                <button class="blog-toggle" onclick="this.parentElement.classList.toggle('expanded')">
                    <span class="show-more">Read full article</span>
                    <span class="show-less">Show less</span>
                </button>
            </article>

"""


def insert_post(html, article_html):
    # 1. Demote the current featured post (do this BEFORE inserting the new one
    #    so the regexes match the old article, not the freshly inserted one).
    html, n = re.subn(
        r'<article class="blog-card blog-card-featured"',
        '<article class="blog-card"',
        html,
        count=1,
    )
    if n == 0:
        raise RuntimeError("Could not find existing featured article to demote.")

    # Remove the old featured post's progress bar (only featured posts have one).
    html = re.sub(
        r'\n\s*<div class="blog-progress" aria-hidden="true"><div class="blog-progress-bar"></div></div>',
        "",
        html,
        count=1,
    )

    # 2. Insert the new featured article at the top of the post list.
    anchor = '<section class="blog-posts">\n        <div class="container">\n'
    if anchor not in html:
        raise RuntimeError("Could not find blog-posts container anchor.")
    return html.replace(anchor, anchor + article_html, 1)


def bump_sitemap(today_str):
    with open(SITEMAP, "r", encoding="utf-8") as f:
        xml = f.read()
    xml = re.sub(r"<lastmod>\d{4}-\d{2}-\d{2}</lastmod>", f"<lastmod>{today_str}</lastmod>", xml)
    with open(SITEMAP, "w", encoding="utf-8") as f:
        f.write(xml)


# --------------------------------------------------------------------------- #
# GitHub Actions output
# --------------------------------------------------------------------------- #
def set_output(**kwargs):
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        return
    with open(out, "a", encoding="utf-8") as f:
        for k, v in kwargs.items():
            v = str(v).replace("\n", " ")
            f.write(f"{k}={v}\n")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(description="Probabilistic auto-blogger.")
    parser.add_argument("--force", action="store_true", help="Bypass the date/probability gate.")
    parser.add_argument("--dry-run", action="store_true", help="Use stub content, no API call.")
    args = parser.parse_args()

    post_now, reason = should_post(force=args.force)
    print(f"[gate] {reason}")

    if not post_now:
        set_output(posted="false")
        return 0

    with open(BLOG_HTML, "r", encoding="utf-8") as f:
        html = f.read()

    post = stub_post() if args.dry_run else generate_post(html)
    print(f"[post] topic={post['topic']!r} title={post['title']!r}")

    article_html = build_article(post)
    html = insert_post(html, article_html)
    with open(BLOG_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    today = date.today()
    bump_sitemap(today.strftime("%Y-%m-%d"))
    write_last_post_date(today)

    set_output(
        posted="true",
        title=post["title"],
        excerpt=post["excerpt"],
        url="https://taylor-riley.com/blog.html",
    )
    print("[done] new featured post written; state + sitemap updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
