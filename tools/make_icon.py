"""Package the selected transparent Hopping Rope logo as a Windows icon."""
from pathlib import Path
from PIL import Image


def main():
    directory = Path(__file__).resolve().parents[1] / 'assets'
    with Image.open(directory / 'hopping-rope-wordmark.png') as source:
        logo = source.convert('RGBA')
    # Fill the icon with the isolated blue-outlined lettering, preserving aspect.
    # Ignore near-transparent padding when choosing the icon viewport.
    bounds = logo.getchannel('A').point(lambda alpha: 255 if alpha >= 128 else 0).getbbox()
    if bounds is None:
        raise ValueError('Wordmark contains no visible pixels')
    left, top, right, bottom = bounds
    logo = logo.crop((max(0,left-2),max(0,top-2),
                      min(logo.width,right+2),min(logo.height,bottom+2)))
    logo.thumbnail((248, 248), Image.Resampling.LANCZOS)
    icon = Image.new('RGBA', (256, 256))
    icon.alpha_composite(logo, ((256-logo.width)//2, (256-logo.height)//2))
    icon.save(directory / 'jump-rope.png')
    icon.save(directory / 'jump-rope.ico', sizes=[(16,16),(24,24),(32,32),
                                               (48,48),(64,64),(128,128),(256,256)])


if __name__ == '__main__':
    main()
