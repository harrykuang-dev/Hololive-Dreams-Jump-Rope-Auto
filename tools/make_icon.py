"""Package the selected transparent Hopping Rope logo as a Windows icon."""
from pathlib import Path
from PIL import Image


def main():
    directory = Path(__file__).resolve().parents[1] / 'assets'
    with Image.open(directory / 'hopping-rope-logo.png') as source:
        logo = source.convert('RGBA')
    # Fill the icon without clipping the rope handles or changing its aspect.
    logo = logo.crop(logo.getbbox())
    logo.thumbnail((248, 248), Image.Resampling.LANCZOS)
    icon = Image.new('RGBA', (256, 256))
    icon.alpha_composite(logo, ((256-logo.width)//2, (256-logo.height)//2))
    icon.save(directory / 'jump-rope.png')
    icon.save(directory / 'jump-rope.ico', sizes=[(16,16),(24,24),(32,32),
                                               (48,48),(64,64),(128,128),(256,256)])


if __name__ == '__main__':
    main()
