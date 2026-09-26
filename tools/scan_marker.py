"""Inspect the controlled player's yellow marker in selected frames."""
import argparse
import cv2

p=argparse.ArgumentParser()
p.add_argument('video')
a=p.parse_args()
cap=cv2.VideoCapture(a.video)
for t in [47,47.8,48,64,65.3,91.6,97.5,98,98.3,99,100,101,102,102.7,103.5,114,138,150]:
    cap.set(cv2.CAP_PROP_POS_MSEC,t*1000)
    ok,frame=cap.read()
    if not ok:
        break
    hsv=cv2.cvtColor(cv2.resize(frame[286:944,526:1700],(960,540)),cv2.COLOR_BGR2HSV)
    mask=cv2.inRange(hsv,(18,110,170),(42,255,255))
    mask[round(.56*540):,:]=0
    mask[:round(.14*540),:]=0
    mask[:,:round(.2*960)]=0
    mask[:,round(.9*960):]=0
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    found=[]
    for c in contours:
        x,y,w,h=cv2.boundingRect(c)
        area=cv2.contourArea(c)
        if 20<=area<=2500 and 7<=w<=50 and 5<=h<=40:
            found.append((round(area),round((x+w/2)/960,3),round((y+h/2)/540,3)))
    print(t,sorted(found,reverse=True)[:5])
cap.release()
