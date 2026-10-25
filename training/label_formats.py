import cv2
import numpy as np

def polygons(mask):
    """Bridge hole contours twice, retaining visible foreground and holes."""
    cs,h=cv2.findContours(mask,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
    if h is None:return []
    result=[]
    for i,c in enumerate(cs):
        if h[0,i,3]!=-1:continue
        p=c[:,0,:].copy()
        if len(p)<3 or cv2.contourArea(p)==0:
            # A one-pixel stroke has no polygon area. A pixel-edge rectangle is
            # the conservative encoding, bounded within the original image.
            x,y,w,hh=cv2.boundingRect(c);x1=min(mask.shape[1]-1,x+max(1,w-1));y1=min(mask.shape[0]-1,y+max(1,hh-1))
            x0=max(0,x1-1) if x1==x else x;y0=max(0,y1-1) if y1==y else y
            p=np.array([[x0,y0],[x1,y0],[x1,y1],[x0,y1]])
        child=h[0,i,2]
        while child!=-1:
            hole=cs[child][:,0,:]
            distance=((p[:,None,:].astype(float)-hole[None,:,:])**2).sum(2)
            a,b=np.unravel_index(distance.argmin(),distance.shape)
            ring=np.r_[hole[b:],hole[:b],hole[b:b+1]]
            p=np.r_[p[:a+1],ring,p[a:a+1],p[a+1:]]
            child=h[0,child,0]
        result.append(p)
    return result

def seg_text(masks):
    h,w=masks[0].shape;lines=[];quality=[]
    for cls,mask in enumerate(masks):
        rebuilt=np.zeros_like(mask)
        ps=polygons(mask)
        if ps:cv2.fillPoly(rebuilt,ps,255)
        union=np.count_nonzero((rebuilt>0)|(mask>0));intersection=np.count_nonzero((rebuilt>0)&(mask>0))
        iou=intersection/union if union else 1.
        if iou<.97:raise ValueError(f'Seg polygon conversion lost mask topology: {iou}')
        quality.append({'class_id':cls,'iou':iou,'changed_pixels':int(np.count_nonzero(rebuilt!=mask))})
        for p in ps:
            lines.append(str(cls)+' '+' '.join(f'{x:.8f}' for x in (p/[w,h]).ravel()))
    return '\n'.join(lines)+'\n',quality

def box_text(masks):
    lines=[]
    for cls,mask in enumerate(masks):
        ys,xs=np.where(mask>0)
        if not len(xs):continue
        h,w=mask.shape;x0,y0,x1,y1=xs.min(),ys.min(),xs.max()+1,ys.max()+1
        values=[(x0+x1)/2/w,(y0+y1)/2/h,(x1-x0)/w,(y1-y0)/h]
        lines.append(str(cls)+' '+' '.join(f'{x:.8f}' for x in values))
    return '\n'.join(lines)+'\n'
