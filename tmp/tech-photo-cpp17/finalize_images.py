from pathlib import Path
import json
import shutil
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '04-编程/语言基础/C++17学习计划/现代 C++11 与 C++14 核心机制'
BACKUP = Path(__file__).parent / 'before-program-correction'
BACKUP.mkdir(parents=True, exist_ok=True)
FONT = 'C:/Windows/Fonts/STXINGKA.TTF'
TITLES = ['值类别与 std::move', '资源转移与返回对象', '转发引用与完美转发', '独占所有权与 C 资源管理', '共享所有权与弱引用', 'Lambda 与回调生命周期', '常用语言工具与易错点', '一帧数据的所有权旅程']
# Rectangles refer to the original 1672x941 images and contain only old watermark ink.
OLD_WATERMARK = [(740,445,930,497),(743,556,929,605),(747,448,925,498),(735,487,941,537),(745,505,929,547),(763,429,904,465),(753,489,919,532),(744,518,928,561)]
HEADER_HEIGHT = [132,128,135,128,124,115,111,127]
REPAIR_CARDS = {1:[(25,137,810,562)],3:[(18,136,875,508),(888,139,1654,508)],4:[(798,129,1213,509)],6:[(18,118,848,487),(864,117,1654,485)],7:[(29,140,889,526)]}
results=[]

def centered_text(draw, center, text, font, fill):
    box=draw.textbbox((0,0),text,font=font)
    pos=(center[0]-(box[0]+box[2])/2, center[1]-(box[1]+box[3])/2)
    draw.text(pos,text,font=font,fill=fill)
    return [pos[0]+box[0],pos[1]+box[1],pos[0]+box[2],pos[1]+box[3]]

for index,path in enumerate(sorted(OUT.glob('[1-8]-*.png'))):
    backup=BACKUP/path.name
    if not backup.exists(): shutil.copy2(path,backup)
    im=Image.open(backup).convert('RGB')
    arr=np.asarray(im).copy()
    x1,y1,x2,y2=OLD_WATERMARK[index]
    crop=arr[y1:y2,x1:x2].astype(np.int16)
    # Only neutral pale gray watermark pixels; retain navy diagram lines and colored cards.
    neutral=(crop.max(2)-crop.min(2)<18)&(crop.min(2)>150)&(crop.mean(2)<237)
    mask=np.zeros(arr.shape[:2],np.uint8)
    mask[y1:y2,x1:x2]=neutral.astype(np.uint8)*255
    mask=cv2.dilate(mask,np.ones((3,3),np.uint8),iterations=1)
    # Exclude navy strokes and their antialias fringe from removal.
    signed=arr.astype(np.int16)
    navy_ink=((signed[:,:,2]>signed[:,:,0]+2)&(signed[:,:,1]>signed[:,:,0]+1))|(signed.mean(2)<145)
    protected=cv2.dilate(navy_ink.astype(np.uint8),np.ones((5,5),np.uint8))>0
    mask[protected]=0
    # Do not let inpainting sample nearby navy card borders: that creates blue streaks.
    work=arr.copy()
    ax1,ay1,ax2,ay2=max(0,x1-16),max(0,y1-16),min(arr.shape[1],x2+16),min(arr.shape[0],y2+16)
    local=work[ay1:ay2,ax1:ax2]
    values=local.astype(np.int16)
    paper_pixels=(values.mean(2)>236)&(values[:,:,0]>=values[:,:,1])&(values[:,:,1]>=values[:,:,2])
    paper_color=np.median(local[paper_pixels],axis=0).astype(np.uint8)
    foreground=(values.mean(2)<210)|(values.max(2)-values.min(2)>24)
    local[foreground]=paper_color
    repaired=cv2.inpaint(work,mask,4,cv2.INPAINT_TELEA)
    arr[mask>0]=repaired[mask>0]
    # Some generated originals already routed card outlines around the old watermark.
    # Rejoin those contours only locally; keep the original hand-drawn outlines elsewhere.
    if index in REPAIR_CARDS:
        contour=Image.new('RGBA',im.size,(0,0,0,0))
        cd=ImageDraw.Draw(contour)
        cleanup=Image.new('L',im.size,0)
        cclean=ImageDraw.Draw(cleanup)
        for card in REPAIR_CARDS[index]:
            left,top,right,bottom=card
            cclean.rounded_rectangle((left-10,top-10,right+10,bottom+10),radius=37,outline=255,width=25)
            cd.rounded_rectangle(card,radius=27,outline=(25,57,78,255),width=3)
        ca=np.asarray(contour)
        region=np.zeros(mask.shape,bool)
        region[max(0,y1-22):min(arr.shape[0],y2+22),max(0,x1-22):min(arr.shape[1],x2+22)]=True
        # Remove old/duplicate curves before drawing the single replacement contour.
        clean_ring=(np.asarray(cleanup)>0)&region
        arr[clean_ring]=paper_color
        restore=(ca[:,:,3]>0)&region
        arr[restore]=ca[:,:,:3][restore]
    # Replace generated title text to make exact font identity with the watermark reproducible.
    hh=HEADER_HEIGHT[index]
    # Far-right header margin is unmarked paper in every input.
    paper=arr[:hh,1605:1665].copy()
    tiled=np.tile(paper,(1,29,1))[:,:arr.shape[1]]
    arr[:hh]=tiled
    im=Image.fromarray(arr).resize((1920,1080),Image.Resampling.LANCZOS)
    if index == 5:
        # Give the exact center a clear band instead of placing watermark on a card border.
        panels=im.crop((0,537,1920,1018)).resize((1920,448),Image.Resampling.LANCZOS)
        paper_band=im.crop((0,495,20,525)).resize((1920,78),Image.Resampling.BILINEAR)
        im.paste(paper_band,(0,492))
        im.paste(panels,(0,570))
    d=ImageDraw.Draw(im)
    navy=(23,54,77)
    title_font=ImageFont.truetype(FONT,96)
    number_font=ImageFont.truetype(FONT,78)
    d.rounded_rectangle((56,12,218,122),radius=24,fill=(247,209,133),outline=navy,width=4)
    centered_text(d,(137,67),f'{index+1}、',number_font,navy)
    title=TITLES[index]
    title_box=d.textbbox((0,0),title,font=title_font)
    d.text((250,67-(title_box[1]+title_box[3])/2),title,font=title_font,fill=navy)
    # Exact 2:1 font size relationship and geometric center of watermark's ink bounding box.
    wm_font=ImageFont.truetype(FONT,48)
    wm_mask=Image.new('L',im.size,0)
    bounds=centered_text(ImageDraw.Draw(wm_mask),(960,540),'code闲录',wm_font,255)
    source=np.asarray(im,dtype=np.float32)
    opacity=np.asarray(wm_mask,dtype=np.float32)/255.0*0.35
    final=np.rint(source*(1-opacity[:,:,None])+204*opacity[:,:,None]).astype(np.uint8)
    meta=PngImagePlugin.PngInfo()
    spec={'title_font':FONT,'title_size_px':96,'watermark_font':FONT,'watermark_size_px':48,'watermark_center':[960,540],'watermark_color':'#CCCCCC','watermark_opacity':0.35,'watermark_rotation':0,'watermark_ink_bbox':bounds,'output_size':[1920,1080],'mode':'RGB'}
    meta.add_text('tech-photo-layout',json.dumps(spec,ensure_ascii=False))
    Image.fromarray(final).save(path,pnginfo=meta)
    results.append({'file':path.name,**spec})
(OUT/'水印参数.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
# Compact contact sheet for checking batch style, full images still need visual review.
sheet=Image.new('RGB',(960,1080),'#F7F3E8')
for i,path in enumerate(sorted(OUT.glob('[1-8]-*.png'))):
    thumb=Image.open(path).resize((480,270),Image.Resampling.LANCZOS)
    sheet.paste(thumb,((i%2)*480,(i//2)*270))
sheet.save(Path(__file__).parent/'contact-sheet.jpg',quality=94)
print(json.dumps({'count':len(results),'directory':str(OUT),'contact_sheet':str(Path(__file__).parent/'contact-sheet.jpg')},ensure_ascii=False))
