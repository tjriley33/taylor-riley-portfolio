"""Generate Open Graph thumbnail image for taylor-riley.com"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os

W, H = 1200, 630
bg = (10, 10, 15)
accent = (99, 102, 241)
accent_light = (129, 140, 248)
white = (232, 232, 237)
muted = (149, 149, 168)

img = Image.new("RGB", (W, H), bg)
draw = ImageDraw.Draw(img)

# Background gradient overlay circles
overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
odraw = ImageDraw.Draw(overlay)

# Accent glow top-left
for r in range(300, 0, -1):
    alpha = int(25 * (r / 300))
    odraw.ellipse([50 - r, -100 - r, 50 + r, -100 + r], fill=(99, 102, 241, alpha))

# Accent glow bottom-right
for r in range(250, 0, -1):
    alpha = int(18 * (r / 250))
    odraw.ellipse([W - 200 - r, H - 50 - r, W - 200 + r, H - 50 + r], fill=(139, 92, 246, alpha))

img.paste(Image.alpha_composite(Image.new("RGBA", (W, H), bg + (255,)), overlay).convert("RGB"))
draw = ImageDraw.Draw(img)

# Grid lines (subtle)
for x in range(0, W, 60):
    draw.line([(x, 0), (x, H)], fill=(255, 255, 255, 5) if hasattr(draw, 'textlength') else (18, 18, 26), width=1)
for y in range(0, H, 60):
    draw.line([(0, y), (W, y)], fill=(18, 18, 26), width=1)

# Try to load headshot
headshot_path = os.path.join(os.path.dirname(__file__), "headshot.png")
if os.path.exists(headshot_path):
    hs = Image.open(headshot_path)
    # Crop to square from top
    size = min(hs.width, hs.height)
    left = (hs.width - size) // 2
    hs = hs.crop((left, 0, left + size, size))
    hs = hs.resize((180, 180), Image.LANCZOS)

    # Create circular mask
    mask = Image.new("L", (180, 180), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, 180, 180], fill=255)

    # Place headshot
    hx, hy = 80, H // 2 - 90
    # Draw accent ring behind
    ring = Image.new("RGBA", (196, 196), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse([0, 0, 195, 195], outline=accent + (180,), width=3)
    img.paste(ring, (hx - 8, hy - 8), ring)
    img.paste(hs, (hx, hy), mask)
    text_x = 300
else:
    text_x = 80

# Fonts - use system fonts
font_paths = [
    "/System/Library/Fonts/SFNSDisplay.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]
font_path_regular = [
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

font_name = load_font(font_paths, 58)
font_subtitle = load_font(font_path_regular, 24)
font_tag = load_font(font_path_regular, 18)
font_badge = load_font(font_path_regular, 16)
font_url = load_font(font_paths, 20)

# Available badge
badge_text = "Available for Director / VP-level roles"
badge_w = draw.textlength(badge_text, font=font_badge) + 24
badge_h = 28
bx, by = text_x, 148
draw.rounded_rectangle([bx, by, bx + badge_w, by + badge_h], radius=14,
                        fill=(20, 30, 25), outline=(52, 211, 153))
draw.text((bx + 12, by + 5), badge_text, fill=(52, 211, 153), font=font_badge)

# Name
draw.text((text_x, 195), "Taylor Riley", fill=white, font=font_name)

# Subtitle
draw.text((text_x, 270), "I build production systems and lead the", fill=muted, font=font_subtitle)
draw.text((text_x, 300), "teams that ship them.", fill=muted, font=font_subtitle)

# Stats bar
stats = [("15+", "Years"), ("28", "Team"), ("5M+", "Filers"), ("37+", "MCP Tools")]
sx = text_x
sy = 370
stat_font_num = load_font(font_paths, 32)
stat_font_label = load_font(font_path_regular, 14)
for num, label in stats:
    draw.text((sx, sy), num, fill=accent_light, font=stat_font_num)
    draw.text((sx, sy + 38), label, fill=muted, font=stat_font_label)
    sx += 140

# Divider line
draw.line([(text_x, 350), (text_x + 520, 350)], fill=(255, 255, 255, 20) if False else (30, 30, 42), width=1)

# URL at bottom
draw.text((text_x, H - 70), "taylor-riley.com", fill=accent_light, font=font_url)

# Accent bar left edge
draw.rectangle([0, 0, 4, H], fill=accent)

out_path = os.path.join(os.path.dirname(__file__), "og-image.png")
img.save(out_path, "PNG", quality=95)
print(f"Saved {out_path} ({os.path.getsize(out_path) // 1024}KB)")
