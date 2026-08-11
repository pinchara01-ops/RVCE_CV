"""Generate raster launch assets from Aperture's canonical mark."""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
BACKGROUND = (5, 5, 5)
GLOW = (214, 181, 107)
WHITE = (245, 242, 235)
MUTED = (174, 169, 158)


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "seguisb.ttf" if bold else "segoeui.ttf"
    path = Path("C:/Windows/Fonts") / name
    return ImageFont.truetype(str(path), size)


def draw_mark(image: Image.Image, box: tuple[int, int, int, int]) -> None:
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = box
    size = right - left
    scale = size / 24

    def point(x: float, y: float) -> tuple[float, float]:
        return left + x * scale, top + y * scale

    width = max(3, round(size * 0.055))
    draw.ellipse(
        (left + 2 * scale, top + 2 * scale, right - 2 * scale, bottom - 2 * scale),
        outline=GLOW,
        width=width,
    )
    for start, end in (
        ((14.31, 8), (20.05, 17.94)),
        ((9.69, 8), (21.17, 8)),
        ((7.38, 12), (13.12, 2.06)),
        ((9.69, 16), (3.95, 6.06)),
        ((14.31, 16), (2.83, 16)),
        ((16.62, 12), (10.88, 21.94)),
    ):
        draw.line((*point(*start), *point(*end)), fill=GLOW, width=width)


def create_icon(size: int, filename: str) -> None:
    image = Image.new("RGB", (size, size), BACKGROUND)
    draw = ImageDraw.Draw(image)
    radius = round(size * 0.22)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=BACKGROUND)
    margin = round(size * 0.125)
    draw_mark(image, (margin, margin, size - margin, size - margin))
    image.save(PUBLIC / filename, optimize=True)


def create_social_card() -> None:
    width, height = 1200, 630
    image = Image.new("RGB", (width, height), BACKGROUND)
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            glow = max(0.0, 1.0 - (((x - 960) / 680) ** 2 + ((y - 110) / 520) ** 2))
            pixels[x, y] = (
                round(5 + 18 * glow),
                round(5 + 14 * glow),
                round(5 + 7 * glow),
            )

    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((54, 54, 1146, 576), radius=38, outline=(55, 48, 34), width=2)
    draw_mark(image, (92, 88, 196, 192))
    draw.text((222, 111), "Aperture", font=font(48, bold=True), fill=WHITE)
    draw.text(
        (92, 258),
        "Search any video archive",
        font=font(58, bold=True),
        fill=WHITE,
    )
    draw.text(
        (92, 332),
        "the way you remember it.",
        font=font(58, bold=True),
        fill=GLOW,
    )
    draw.text(
        (94, 430),
        "Text · voice · images · reference clips · 13 Indian languages",
        font=font(26),
        fill=MUTED,
    )
    draw.text((94, 504), "Find the exact playable moment.", font=font(25), fill=WHITE)
    image.save(PUBLIC / "og-aperture.png", optimize=True)


if __name__ == "__main__":
    PUBLIC.mkdir(parents=True, exist_ok=True)
    create_icon(180, "aperture-icon-180.png")
    create_icon(512, "aperture-icon-512.png")
    create_social_card()
