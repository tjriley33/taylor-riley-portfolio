"""Generate the social preview from the brand's dark theme. Requires Pillow."""
from pathlib import Path
import re
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
blocks = re.findall(r':root\s*\{([^}]+)', (ROOT/'styles/tokens.css').read_text())
colors = dict(re.findall(r'--([a-z]+):\s*(#[0-9a-f]{6})', blocks[1]))
img = Image.new('RGB', (1200, 630), colors['bg'])
draw = ImageDraw.Draw(img)
def font(size, bold=False):
    name = 'Arial Bold.ttf' if bold else 'Arial.ttf'
    candidates = [Path('/System/Library/Fonts/Supplemental')/name,
                  Path('/usr/share/fonts/truetype/dejavu')/('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')]
    for path in candidates:
        if path.exists(): return ImageFont.truetype(str(path), size)
    raise RuntimeError('Install Arial or DejaVu Sans to generate the social image')
draw.rectangle((72,72,78,554), fill=colors['accent'])
draw.text((110,78),'Taylor Riley', font=font(30,True), fill=colors['text'])
draw.text((110,172),'Complex rules.', font=font(68,True), fill=colors['text'])
draw.text((110,252),'Software people can verify.', font=font(62,True), fill=colors['text'])
draw.text((110,378),'Tax software. AI tools. Technical leadership.', font=font(30), fill=colors['muted'])
draw.text((110,510),'taylor-riley.com', font=font(25), fill=colors['accent'])
img.save(ROOT/'og-image.png')
print('Saved og-image.png')
