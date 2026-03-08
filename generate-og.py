"""Generate Open Graph thumbnail image for taylor-riley.com"""
from PIL import Image, ImageDraw, ImageFont
import os

DIR = os.path.dirname(__file__)
W, H = 1200, 630

accent = (99, 102, 241)
accent_light = (129, 140, 248)
white = (232, 232, 237)
muted = (149, 149, 168)
dark_muted = (107, 107, 128)

# Base image with smooth gradient background
img = Image.new("RGB", (W, H), (10, 10, 15))
draw = ImageDraw.Draw(img)

# Smooth radial glows (no grid lines)
overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
odraw = ImageDraw.Draw(overlay)

for r in range(400, 0, -2):
    a = int(20 * (r / 400))
    odraw.ellipse([80 - r, -150 - r, 80 + r, -150 + r], fill=(99, 102, 241, a))

for r in range(350, 0, -2):
    a = int(12 * (r / 350))
    odraw.ellipse([W - 150 - r, H + 50 - r, W - 150 + r, H + 50 + r], fill=(139, 92, 246, a))

for r in range(200, 0, -2):
    a = int(8 * (r / 200))
    odraw.ellipse([W // 2 - r, H // 2 - r, W // 2 + r, H // 2 + r], fill=(59, 130, 246, a))

img.paste(Image.alpha_composite(Image.new("RGBA", (W, H), (10, 10, 15, 255)), overlay).convert("RGB"))
draw = ImageDraw.Draw(img)

# Load headshot
headshot_path = os.path.join(DIR, "headshot.png")
text_x = 80
if os.path.exists(headshot_path):
    hs = Image.open(headshot_path)
    size = min(hs.width, hs.height)
    left = (hs.width - size) // 2
    hs = hs.crop((left, 0, left + size, size))
    hs = hs.resize((160, 160), Image.LANCZOS)

    mask = Image.new("L", (160, 160), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, 160, 160], fill=255)

    hx, hy = 80, H // 2 - 80

    # Accent ring
    ring = Image.new("RGBA", (176, 176), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse([0, 0, 175, 175], outline=accent + (140,), width=2)
    img.paste(ring, (hx - 8, hy - 8), ring)
    img.paste(hs, (hx, hy), mask)
    text_x = 280

# Fonts
font_paths_bold = [
    "/System/Library/Fonts/SFNSDisplay.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]
font_paths_regular = [
    "/System/Library/Fonts/SFNSText.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]

def load_font(paths, size):
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()

font_name = load_font(font_paths_bold, 54)
font_sub = load_font(font_paths_regular, 22)
font_badge = load_font(font_paths_regular, 15)
font_stat_num = load_font(font_paths_bold, 28)
font_stat_label = load_font(font_paths_regular, 13)
font_url = load_font(font_paths_bold, 18)

# Badge
badge_text = "Available for Director / VP-level roles"
bw = draw.textlength(badge_text, font=font_badge) + 24
bx, by = text_x, 145
draw.rounded_rectangle([bx, by, bx + bw, by + 26], radius=13,
                        fill=(20, 35, 28), outline=(52, 211, 153))
draw.text((bx + 12, by + 4), badge_text, fill=(52, 211, 153), font=font_badge)

# Name
draw.text((text_x, 190), "Taylor Riley", fill=white, font=font_name)

# Subtitle
draw.text((text_x, 258), "I build production systems and lead the", fill=muted, font=font_sub)
draw.text((text_x, 286), "teams that ship them.", fill=muted, font=font_sub)

# Thin separator
draw.line([(text_x, 335), (text_x + 480, 335)], fill=(40, 40, 55), width=1)

# Stats
stats = [("15+", "Years"), ("28", "Team"), ("5M+", "Filers"), ("37+", "MCP Tools")]
sx, sy = text_x, 355
for num, label in stats:
    draw.text((sx, sy), num, fill=accent_light, font=font_stat_num)
    draw.text((sx, sy + 34), label, fill=dark_muted, font=font_stat_label)
    sx += 130

# URL bottom
draw.text((text_x, H - 60), "taylor-riley.com", fill=accent_light, font=font_url)

# Accent bar left edge
draw.rectangle([0, 0, 3, H], fill=accent)

img.save(os.path.join(DIR, "og-image.png"), "PNG", quality=95)
print("Saved og-image.png")
