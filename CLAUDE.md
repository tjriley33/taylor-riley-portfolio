# Repository instructions

@BRAND.md

Read and enforce BRAND.md before generating or editing any copy, documentation, code, metadata, visual assets, or posts. Check the final diff against its evidence, vocabulary, and visual rules. BRAND.md is the editorial source of truth in this repository.

- This is an existing semantic HTML site, served by Cloudflare Workers Static Assets. Keep the homepage fast and usable without JavaScript.
- Homepage: index.html. Tokens: styles/tokens.css. Layout: styles/portfolio.css. Logos: public/logo.svg and public/favicon.svg. These are served at /public/ because the asset root is the repository root.
- Legacy blog, game, styles.css and script.js remain for existing URLs. Do not use the legacy blog as factual evidence.
- Run `python3 scripts/check-brand.py` before completion. Also inspect light and dark layouts on a narrow phone and desktop, keyboard focus, and 200% zoom after visual changes.
- Keep BRAND.md, rendered copy, social metadata, and generate-og.py aligned. Regenerate og-image.png after changing social copy or tokens.
- `.assetsignore` excludes source, instructions, drafts, and tooling from hosting. `.gitignore` keeps drafts out of this public repository.
- `/brand-post` lives in .claude/commands/brand-post.md. Run it with notes, a file path, or a git revision/range. Draft only; no posting or deployment from that command.
- GitHub no longer generates or publishes blog posts on a schedule. The old scripts are historical, not the current editorial workflow.
