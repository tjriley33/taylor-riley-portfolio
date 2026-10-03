# Taylor Riley

Personal brand system and static portfolio for https://taylor-riley.com.

## Preview

```sh
python3 -m http.server 8080 --bind 127.0.0.1
```

Open http://127.0.0.1:8080. No build, framework, remote fonts, or runtime JavaScript is required for the homepage. The local development server serves the working tree, including ignored drafts; bind it only to loopback.

## Edit

- `BRAND.md`: positioning, three pillars, voice, vocabulary, and evidence boundaries.
- `CLAUDE.md`: imports the brand rules for future Claude Code sessions.
- `index.html`: homepage copy and metadata.
- `styles/tokens.css`: light/dark neutral palette, blue accent, type and spacing.
- `styles/portfolio.css`: responsive layout and focus styles.
- `public/logo.svg`, `public/favicon.svg`: TR monogram on a 16-unit grid.
- `generate-og.py`: social image generator (Python with Pillow installed).
- `.claude/commands/brand-post.md`: source-grounded local drafting workflow.

Run `python3 scripts/check-brand.py`. Review the page on desktop and phone in both themes, at 200% zoom, and by keyboard. The automated contrast check covers the declared text and focus colors; it is not a full accessibility certification.

## Draft an article or post

```text
/brand-post article notes/form-identity.md
/brand-post linkedin HEAD~2..HEAD
/brand-post article Matching on display names broke when the title changed. We introduced a stable ID and checked the mappings before writing them.
```

The command accepts notes, paths, and git revisions. It saves reviewed prose and source metadata to `posts/drafts/<title>.md`, handles filename collisions, and never publishes. Drafts are excluded from both git and deployment. Empty input prompts for material rather than inventing it. Command syntax follows the [Claude Code command documentation](https://code.claude.com/docs/en/skills).

The homepage names two actual local drafts. Their bodies stay private until Taylor reviews them. After publication, replace each draft label with a working article link, publication date, and reading time calculated from the final body.

## Deploy

Cloudflare Workers Builds deploys pushes to `main`; configuration is in `wrangler.jsonc`. The repository root is the asset root, so SVG URLs start with `/public/`. `.assetsignore` excludes tooling, instructions, and drafts. Local git commits alone do not deploy.

The old blog and game URLs retain their original files and styles. The resume PDF is retained for existing direct links but is not advertised on the new homepage because its claims need reconciliation with the newer career evidence audit. The legacy auto-blog scripts remain as historical code; the GitHub workflow now validates the brand instead of generating or sending posts.
