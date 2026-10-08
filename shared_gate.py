"""Exact old HUD checks sharing one resize for the same immutable capture."""
import cv2
import numpy as np
from vision import RoundGate

class SharedRoundGate(RoundGate):
    _source=None
    _normalized=None

    @classmethod
    def reset_cache(cls):
        cls._source=cls._normalized=None

    @classmethod
    def normalized(cls,frame):
        # DXGI grabs use copy=True: each fresh capture owns a new ndarray.
        # Hold a strong source reference so object IDs cannot be reused.
        if frame is not cls._source:
            cls._source=frame
            cls._normalized=cv2.resize(frame,(960,540))
        return cls._normalized

    @classmethod
    def gameplay_visible(cls,frame):
        if frame.size==0:return False
        normalized=cls.normalized(frame)
        hearts=cv2.inRange(cv2.cvtColor(normalized[190:235,55:155],cv2.COLOR_BGR2HSV),(35,100,130),(85,255,255))
        button=cv2.cvtColor(normalized[375:490,750:895],cv2.COLOR_BGR2HSV)
        jump=cv2.inRange(button,(20,100,180),(42,255,255))
        blue_button=cv2.inRange(button,(85,80,80),(125,255,255))
        score=cv2.inRange(cv2.cvtColor(normalized[45:125,35:155],cv2.COLOR_BGR2HSV),(0,0,210),(180,65,255))
        return (np.count_nonzero(hearts)>=70 and np.count_nonzero(jump)>=250
                and np.count_nonzero(blue_button)>=200 and np.count_nonzero(score)>=100)

    @classmethod
    def player_ready(cls,frame):
        if frame.size==0:return False
        roi=cls.normalized(frame)[95:250,500:600]
        hsv=cv2.cvtColor(roi,cv2.COLOR_BGR2HSV)
        region=cv2.inRange(hsv,(18,110,170),(42,255,255))
        contours,_=cv2.findContours(region,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area=cv2.contourArea(contour)
            x,y,width,height=cv2.boundingRect(contour)
            if 22<=area<=110 and 6<=width<=22 and 5<=height<=17:
                center_x=(500+x+width/2)/960
                center_y=(95+y+height/2)/540
                if .53<=center_x<=.60 and .20<=center_y<=.45:return True
        return False

    @classmethod
    def jump_position(cls,frame):
        if frame.size==0:return None
        roi=cls.normalized(frame)[375:490,750:895]
        hsv=cv2.cvtColor(roi,cv2.COLOR_BGR2HSV)
        mask=cv2.inRange(hsv,(20,100,180),(42,255,255))
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        if not contours:return None
        contour=max(contours,key=cv2.contourArea)
        if cv2.contourArea(contour)<150:return None
        m=cv2.moments(contour)
        if not m['m00']:return None
        return ((750+m['m10']/m['m00'])/960,(375+m['m01']/m['m00'])/540)
