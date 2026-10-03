# Editorial workflow

The scheduled generator has been retired. `.github/workflows/auto-blog.yml` now runs brand checks on pushes, pull requests, and manual invocation. It has no publishing or email step.

Use `/brand-post article <notes>` or `/brand-post linkedin <notes>` in Claude Code at the repository root. Drafts are saved under `posts/drafts/`, ignored by git, and excluded from Cloudflare assets. Taylor reviews and publishes the final copy himself.

`auto_blog.py` and `send_notification.py` remain as historical code. Do not run them to generate or distribute new writing. Existing essays remain at their original URLs; they have not been revalidated as autobiographical evidence.
