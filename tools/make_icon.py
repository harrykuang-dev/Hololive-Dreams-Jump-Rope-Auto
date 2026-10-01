"""Render an original geometric jump-rope icon; no game artwork is copied."""
from pathlib import Path
import struct
import cv2
import numpy as np


def render(size):
    image = np.zeros((size,size,4),np.uint8)
    scale = size/256
    point = lambda x,y:(round(x*scale),round(y*scale))
    blue,white = (192,103,0,255),(255,255,255,255)
    for a,b in (((56,8),(200,248)),((8,56),(248,200))):
        cv2.rectangle(image,point(*a),point(*b),blue,-1)
    for x,y in ((56,56),(200,56),(56,200),(200,200)):
        cv2.circle(image,point(x,y),round(48*scale),blue,-1,cv2.LINE_AA)
    thickness = max(1,round(13*scale))
    cv2.ellipse(image,point(128,127),point(76,72),0,195,345,white,thickness,cv2.LINE_AA)
    for a,b in (((55,110),(74,166)),((201,110),(182,166))):
        cv2.line(image,point(*a),point(*b),white,thickness,cv2.LINE_AA)
    for a,b in (((77,177),(84,199)),((179,177),(172,199))):
        cv2.line(image,point(*a),point(*b),white,max(1,round(22*scale)),cv2.LINE_AA)
    return image


def main():
    directory = Path(__file__).resolve().parents[1]/'assets'
    directory.mkdir(exist_ok=True)
    sizes = (32,48,128,256)
    images = [cv2.imencode('.png',render(size))[1].tobytes() for size in sizes]
    offset = 6+16*len(sizes)
    entries = []
    for size,png in zip(sizes,images):
        entries.append(struct.pack('<BBBBHHII',size%256,size%256,0,0,1,32,len(png),offset))
        offset += len(png)
    (directory/'jump-rope.ico').write_bytes(struct.pack('<HHH',0,1,len(sizes))+b''.join(entries)+b''.join(images))
    (directory/'jump-rope.png').write_bytes(images[-1])


if __name__ == '__main__':
    main()
