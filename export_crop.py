import fitz, sys, os
doc=fitz.open('攻守記錄表掃描檔.pdf')
LAND={4:270,12:270}                       # 橫式頁需旋轉成直式
BANDS={1:(0.00,0.34),2:(0.33,0.66),3:(0.62,1.00)}
os.makedirs('cuts',exist_ok=True)
def crop(page,slot,zoom=3.2):
    p=doc[page-1]; p.set_rotation(LAND.get(page,0)); r=p.rect
    y0,y1=BANDS[slot]
    clip=fitz.Rect(0,r.height*y0,r.width,r.height*y1)
    pix=p.get_pixmap(matrix=fitz.Matrix(zoom,zoom),clip=clip)
    out=f'cuts/p{page}s{slot}.png'; pix.save(out); p.set_rotation(0); return out
if __name__=='__main__':
    for a in sys.argv[1:]:
        pg,sl=a.lstrip('p').split('s'); print(crop(int(pg),int(sl)))
