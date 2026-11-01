from pathlib import Path
import json
import shutil
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
BACKUP = ROOT / '_水印修复前'
BACKUP.mkdir(exist_ok=True)
FONT = 'C:/Windows/Fonts/FZSTK.TTF'
TITLE_SIZE = 68
WATERMARK_SIZE = TITLE_SIZE / 2
SCALE = 4
TITLES = ['设备接口与多态', 'RAII 与资源生命周期', 'Three / Five / Zero 如何选择', '异常与失败后的状态', '运算符与显式转换', 'UniqueFd：独占句柄的完整路径']
OLD_BOXES = [(730,425,940,473), (758,438,923,480), (727,401,940,451), (729,472,940,521), (728,487,946,537), (727,473,944,525)]

def glyph(text, size, stroke):
    font = ImageFont.truetype(FONT, round(size*SCALE))
    bounds = font.getbbox(text, stroke_width=stroke)
    mask = Image.new('L', (bounds[2]-bounds[0]+16, bounds[3]-bounds[1]+16))
    ImageDraw.Draw(mask).text((8-bounds[0],8-bounds[1]),text,font=font,fill=255,stroke_width=stroke)
    return mask.crop(mask.getbbox())

def apply_text(rgb, text, size, stroke, position, color, opacity=1.0, centered=False):
    small = glyph(text,size,stroke)
    layer = Image.new('L',(rgb.shape[1]*SCALE,rgb.shape[0]*SCALE))
    if centered:
        # Center the actual glyph ink bounds, rather than a font's baseline box.
        px = position[0]*SCALE-small.width/2
        py = position[1]*SCALE-small.height/2
    else:
        px,py = (round(v*SCALE) for v in position)
    layer = small.transform(layer.size,Image.Transform.AFFINE,(1,0,-px,0,1,-py),resample=Image.Resampling.BICUBIC)
    coverage = np.asarray(layer.resize((rgb.shape[1],rgb.shape[0]),Image.Resampling.LANCZOS),dtype=np.float32)/255
    alpha = coverage[:,:,None]*opacity
    return np.clip(np.rint(rgb*(1-alpha)+np.array(color)[None,None,:]*alpha),0,255).astype(np.uint8), [px/SCALE,py/SCALE,(px+small.width)/SCALE,(py+small.height)/SCALE]

report=[]
for index,title in enumerate(TITLES,1):
    target=next(ROOT.glob(f'{index}-*.png'))
    original=BACKUP/target.name
    if not original.exists():
        shutil.copy2(target,original)
    rgb=np.array(Image.open(original).convert('RGB'))
    height,width=rgb.shape[:2]
    mask=np.zeros((height,width),np.uint8)
    x0,y0,x1,y1=OLD_BOXES[index-1]
    block=rgb[y0:y1,x0:x1].astype(np.int16)
    gray=(block.max(axis=2)-block.min(axis=2)<22)&(block.min(axis=2)<237)&(block.max(axis=2)>115)
    mask[y0:y1,x0:x1]=gray.astype(np.uint8)*255
    mask=cv2.dilate(mask,np.ones((3,3),np.uint8))
    # Keep dark navy technical text/lines and teal diagram components intact.
    protect=(rgb[:,:,2].astype(int)-rgb[:,:,0].astype(int)>5)|(rgb[:,:,1].astype(int)-rgb[:,:,0].astype(int)>10)|(rgb.min(axis=2)<90)
    mask[protect]=0
    # Restore the paper under the former neutral-gray watermark, preserving
    # the original colored text and diagram strokes pixel for pixel.
    original_block=rgb[y0:y1,x0:x1].copy()
    for row in range(y0,y1):
        samples=rgb[max(0,row-2):min(height,row+3),x0-18:x1+18].reshape(-1,3)
        pale=(samples[:,0]>239)&(samples[:,1]>237)&(samples[:,2]>225)&(samples[:,0]>=samples[:,2])
        paper_color=np.median(samples[pale],axis=0) if pale.any() else np.array([250,248,243])
        selected=mask[row,x0:x1]>0
        rgb[row,x0:x1][selected]=paper_color.astype(np.uint8)
    keep=protect[y0:y1,x0:x1]
    rgb[y0:y1,x0:x1][keep]=original_block[keep]
    if index==6:
        # Repair the existing move-result card's interrupted lower-left border.
        rgb[489:507,869:944]=np.median(rgb[512:519,870:942],axis=(0,1)).astype(np.uint8)
        canvas=Image.fromarray(rgb).resize((width*SCALE,height*SCALE),Image.Resampling.LANCZOS)
        pen=ImageDraw.Draw(canvas)
        points=[(850.75,477),(850.75,483)]
        for t in np.linspace(0,1,32):
            points.append(((1-t)**2*850.75+2*(1-t)*t*850.75+t*t*872,(1-t)**2*483+2*(1-t)*t*501.5+t*t*501.5))
        points.append((948,501.5))
        pen.line([(round(x*SCALE),round(y*SCALE)) for x,y in points],fill=(20,49,77),width=12,joint='curve')
        rgb=np.asarray(canvas.resize((width,height),Image.Resampling.LANCZOS)).copy()
    # Re-set the existing main title with the same font used for the watermark.
    right=1218 if index==6 else 1648
    # A clean paper sample avoids inpainting halos around the former title.
    paper=rgb[8:104,1650:1664].mean(axis=1).astype(np.uint8)
    rgb[8:104,222:right]=paper[:,None,:]
    rgb,title_bounds=apply_text(rgb,title,TITLE_SIZE,4,(230,19),(32,59,87))
    rgb,watermark_bounds=apply_text(rgb,'code闲录',WATERMARK_SIZE,2,(width/2,height/2),(204,204,204),.35,True)
    Image.fromarray(rgb,'RGB').save(target)
    report.append(dict(file=target.name,size=[width,height],mode='RGB',font=FONT,title_font_size=TITLE_SIZE,watermark_font_size=WATERMARK_SIZE,watermark_center=[width/2,height/2],watermark_ink_bounds=watermark_bounds,color='#CCCCCC',opacity=.35,rotation=0,title_ink_bounds=title_bounds))
(ROOT/'水印参数.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
