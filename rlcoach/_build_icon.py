"""
Converts app_icon.png → rlcoach.ico (multi-size) for the PyInstaller build.
Run standalone:  python -m rlcoach._build_icon
"""
from pathlib import Path


def make_ico(
    source_png: str = "app_icon.png",
    output_ico: str = "rlcoach.ico",
) -> None:
    from PIL import Image

    src = Path(source_png)
    if not src.exists():
        raise FileNotFoundError(f"Source PNG not found: {src.resolve()}")

    img = Image.open(src).convert("RGBA")

    # Pillow's ICO writer accepts a 'sizes' list and handles the downscaling itself.
    # This is the correct API — append_images does not work for ICO multi-size.
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save(output_ico, format="ICO", sizes=sizes)
    print(f"  Icon saved: {output_ico}  ({len(sizes)} sizes from {src.name})")


if __name__ == "__main__":
    make_ico()
