
from PIL import Image, ImageDraw

SIZE = 256

image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)

# Main blue document.
draw.rounded_rectangle(
    (42, 20, 205, 232),
    radius=20,
    fill=(39, 127, 192, 255)
)

# White document page.
draw.rounded_rectangle(
    (57, 35, 190, 216),
    radius=10,
    fill=(255, 255, 255, 255)
)

# Folded corner.
draw.polygon(
    [(151, 35), (190, 74), (151, 74)],
    fill=(195, 220, 240, 255)
)

# Image frame.
draw.rounded_rectangle(
    (72, 91, 175, 165),
    radius=8,
    fill=(225, 239, 249, 255)
)

# Sun.
draw.ellipse(
    (140, 101, 158, 119),
    fill=(244, 181, 64, 255)
)

# Mountains.
draw.polygon(
    [(78, 153), (109, 119), (130, 143),
     (148, 126), (170, 153)],
    fill=(48, 145, 103, 255)
)

# PDF lettering.
draw.text(
    (83, 177),
    "PDF",
    fill=(39, 127, 192, 255),
    stroke_width=0
)

image.save(
    "imgtopdf.ico",
    format="ICO",
    sizes=[
        (16, 16),
        (24, 24),
        (32, 32),
        (48, 48),
        (64, 64),
        (128, 128),
        (256, 256)
    ]
)

print("imgtopdf.ico created successfully.")
