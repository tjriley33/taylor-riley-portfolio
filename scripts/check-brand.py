#!/usr/bin/env python3
"""Dependency-free checks for brand copy, links, contrast, and draft boundaries."""
from pathlib import Path
from html.parser import HTMLParser
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
errors = []

class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.refs, self.words = [], [], []
        self.h1 = 0
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if 'id' in a: self.ids.append(a['id'])
        if tag == 'h1': self.h1 += 1
        for key in ('href', 'src'):
            if key in a: self.refs.append(a[key])
    def handle_data(self, data): self.words.append(data)

page = Page()
page.feed((ROOT / 'index.html').read_text())
assert page.h1 == 1, 'Homepage must have exactly one h1'
assert len(page.ids) == len(set(page.ids)), 'Duplicate IDs'
for ref in page.refs:
    if ref.startswith(('http:', 'https:', 'mailto:')): continue
    if ref.startswith('#'):
        if ref[1:] not in page.ids: errors.append(f'Missing anchor {ref}')
    elif not (ROOT / ref.split('#')[0]).is_file(): errors.append(f'Missing file {ref}')

banned = re.compile(r'\b(leverage|utilize|synergy|revolutionary|game-changing|thought leadership)\b', re.I)
copy = [('index.html', ' '.join(page.words))]
for draft in (ROOT / 'posts/drafts').glob('*.md'):
    text = draft.read_text()
    parts = text.split('---', 2)
    if len(parts) != 3:
        errors.append(f'{draft.name}: missing frontmatter')
        continue
    meta, body = parts[1:]
    for key in ('title:', 'date:', 'format:', 'status: draft', 'reading_minutes:', 'sources:', 'review_notes:'):
        if key not in meta: errors.append(f'{draft.name}: missing {key}')
    copy.append((draft.name, body))
for name, text in copy:
    if '\u2014' in text: errors.append(f'{name}: em dash')
    if banned.search(text): errors.append(f'{name}: avoid {banned.search(text).group()}')
    if re.search(r'lorem ipsum|\bTODO\b|\bTBD\b', text, re.I): errors.append(f'{name}: placeholder')

css = (ROOT / 'styles/tokens.css').read_text()
blocks = re.findall(r':root\s*\{([^}]+)', css)
def luminance(color):
    values = [int(color[i:i+2], 16)/255 for i in (1,3,5)]
    values = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in values]
    return sum(v*w for v,w in zip(values, (.2126,.7152,.0722)))
def contrast(a,b):
    l = sorted((luminance(a),luminance(b)))
    return (l[1]+.05)/(l[0]+.05)
for mode, block in zip(('light','dark'), blocks):
    colors = dict(re.findall(r'--([a-z]+):\s*(#[0-9a-f]{6})', block))
    for bg in ('bg','surface'):
        for fg in ('text','muted','accent'):
            ratio = contrast(colors[fg],colors[bg])
            print(f'{mode}: {fg}/{bg} = {ratio:.2f}:1')
            if ratio < 4.5: errors.append(f'{mode} {fg}/{bg}: AA contrast failure')
assert len(blocks) == 2, 'Both color modes required'
for file in ('public/logo.svg','public/favicon.svg'):
    svg = ET.parse(ROOT/file).getroot()
    assert svg.attrib['viewBox'] == '0 0 16 16'
    assert contrast('#ffffff','#174fc4') >= 4.5
for name in ('.claude','posts','BRAND.md','CLAUDE.md','scripts'):
    if name not in (ROOT/'.assetsignore').read_text().splitlines(): errors.append(f'Asset exclusion missing: {name}')
if 'posts/drafts/*' not in (ROOT/'.gitignore').read_text(): errors.append('Drafts must be gitignored')
workflow = (ROOT/'.github/workflows/auto-blog.yml').read_text()
if 'cron:' in workflow or 'python auto_blog.py' in workflow: errors.append('Unreviewed publishing enabled')
command = (ROOT/'.claude/commands/brand-post.md').read_text()
for part in ('$ARGUMENTS','BRAND.md','posts/drafts/','Sentence 1'):
    if part not in command: errors.append(f'Command missing {part}')
if errors:
    raise SystemExit('\n'.join(errors))
print('Brand, contrast, link, SVG, and draft-boundary checks passed.')
