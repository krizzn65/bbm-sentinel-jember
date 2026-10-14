"""Bulletin image card (v0.7): the daily bulletin as a forwardable
PNG, so it can travel through HIMANIKA and neighbourhood groups -
and every forward is also a recruitment poster for the citizen-eye
network whose photos make the system smarter.

Rendered from the same data as the text bulletin (no second source
of truth): risk percentage, per-fuel status, station groups and the
council peak line. Calm colours; the band colour follows the risk
percentage, never alarm-red unless the index truly is."""
from pathlib import Path

W, H = 1080, 1350
MARGIN = 64


def _band(risk):
    if risk >= 80:
        return (178, 34, 34)
    if risk >= 60:
        return (208, 110, 20)
    if risk >= 40:
        return (196, 148, 0)
    return (34, 139, 84)


def render_card(out_path, *, risk, hari, jam, fuel_lines, avoid,
                queueing, fine, peak_line, footer_note):
    from PIL import Image, ImageDraw, ImageFont

    def font(size, bold=False):
        name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        for base in ("/usr/share/fonts/truetype/dejavu/",):
            p = Path(base) / name
            if p.exists():
                return ImageFont.truetype(str(p), size)
        return ImageFont.load_default()

    img = Image.new("RGB", (W, 1750), (250, 250, 247))
    d = ImageDraw.Draw(img)
    band = _band(risk)
    d.rectangle([0, 0, W, 300], fill=band)
    d.text((MARGIN, 44), "INFO BBM JEMBER", font=font(44, True),
           fill=(255, 255, 255))
    d.text((MARGIN, 104), hari, font=font(30), fill=(255, 255, 255))
    d.text((MARGIN, 158), f"Tingkat risiko: {risk:.0f}%",
           font=font(76, True), fill=(255, 255, 255))
    d.text((MARGIN, 252), f"Pembaruan pukul {jam} WIB",
           font=font(26), fill=(255, 255, 255))

    y = 340

    def section(title, lines, color=(30, 30, 30)):
        nonlocal y
        d.text((MARGIN, y), title, font=font(34, True), fill=(20, 60, 40))
        y += 50
        for ln in lines:
            d.text((MARGIN + 8, y), f"•  {ln}", font=font(30), fill=color)
            y += 44
        y += 22

    if fuel_lines:
        section("Bensin yang lagi susah dicari", fuel_lines)
    if avoid:
        section("Paling parah, hindari dulu", avoid)
    if queueing:
        section("Antre, tapi masih jalan", queueing)
    if fine:
        section("Masih relatif lancar", fine[:5])
    if peak_line:
        d.line([MARGIN, y, W - MARGIN, y], fill=(180, 180, 180), width=2)
        y += 24
        # simple word wrap at ~52 chars
        words, cur = peak_line.split(), ""
        for w_ in words:
            if len(cur) + len(w_) + 1 > 52:
                d.text((MARGIN, y), cur, font=font(28), fill=(40, 40, 40))
                y += 40
                cur = w_
            else:
                cur = f"{cur} {w_}".strip()
        if cur:
            d.text((MARGIN, y), cur, font=font(28), fill=(40, 40, 40))
            y += 40
    # Canvas height follows the content - a long bulletin must never
    # clip under the footer band.
    final_h = max(1080, y + 48 + 120)
    img = img.crop((0, 0, W, final_h))
    d = ImageDraw.Draw(img)
    d.rectangle([0, final_h - 120, W, final_h], fill=(38, 50, 44))
    d.text((MARGIN, final_h - 92), footer_note, font=font(25),
           fill=(255, 255, 255))
    d.text((MARGIN, final_h - 52),
           "Melihat antrean di SPBU? Foto dan kirim ke HIMANIKA.",
           font=font(25), fill=(255, 255, 255))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    return out_path
