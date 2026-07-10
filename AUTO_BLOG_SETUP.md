# Auto Blog Poster — Setup

This runs your blog auto-poster **in the cloud via GitHub Actions**, so it works
whether or not your computer (or the Claude app) is running.

## What got added

| File | Purpose |
|------|---------|
| `.github/workflows/auto-blog.yml` | Runs daily at 14:00 UTC (~10 AM Virginia / EDT). Gates, generates, commits, pushes, emails. |
| `auto_blog.py` | Decision logic + post generation (calls the Anthropic API) + inserts the featured post + bumps `sitemap.xml`. |
| `.github/last_post_date.txt` | Tracks the exact last-post date (seeded `2026-06-20`) so the 7/14-day math is precise. |

The decision logic each run: **< 7 days** since last post → do nothing. **7–13 days** → 20% chance to post. **≥ 14 days** → must post.

## One-time setup (do these once)

### 1. Add the two repository secrets

The workflow needs your Anthropic API key and your Gmail app password. Reuse the
same `SMTP_PASSWORD` value that's already in your local `.env`.

Using the GitHub CLI from the repo folder:

```bash
gh secret set ANTHROPIC_API_KEY      # paste your key from console.anthropic.com
gh secret set SMTP_PASSWORD          # paste the SMTP_PASSWORD value from your .env
```

Or via the web UI: **Repo → Settings → Secrets and variables → Actions → New repository secret**, adding `ANTHROPIC_API_KEY` and `SMTP_PASSWORD`.

### 2. Allow Actions to push commits

**Repo → Settings → Actions → General → Workflow permissions →** select
**“Read and write permissions”** → Save. (The workflow commits the new post back to `main`.)

### 3. Push the new files

```bash
git add auto_blog.py send_notification.py .github AUTO_BLOG_SETUP.md
git commit -m "Add cloud auto-blog poster (GitHub Actions)"
git push
```

## Test it

Trigger a run manually with the gate bypassed:
**Repo → Actions → “Auto Blog Poster” → Run workflow → set `force` = true → Run.**

Or via CLI: `gh workflow run "Auto Blog Poster" -f force=true`

A successful forced run will write a new featured post, push the commit, and email you.

## Notes

- **Timezone:** GitHub cron is UTC-only. `0 14 * * *` is 10 AM during EDT (summer) and 9 AM during EST (winter). Change the hour in the workflow if you want it pinned.
- **Model/cost:** Each *posting* run makes one Anthropic API call (a few cents). Skipped days make zero API calls — the gate exits first.
- **Model override:** set an `ANTHROPIC_MODEL` secret/variable to pin a different model (defaults to `claude-sonnet-4-6`).
- The old Claude desktop scheduled task (`auto-blog-poster`) is paused, so the two won't both post.
