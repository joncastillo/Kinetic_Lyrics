"""Measured free word placement with collision correction inside a reading area."""
from core.imaging import turn
import math
from PIL import Image,ImageDraw
from render.typography_settings import KINETIC_TEXT_SCALE


def build_layout(line,choices,scene,width,height,font_loader,font_scale=1.25,botanical=False,_fit_depth=0):
    palette=scene['colors'];words=[]
    base=max(18,min(height*.11,width*.07))*font_scale*KINETIC_TEXT_SCALE
    for index,(word,choice) in enumerate(zip(line['words'],choices)):
        size=max(10,round(base*choice['scale']))
        label=word['text'].upper();color={'base':palette[0],'accent':palette[1],'red':'#ef4c54'}[choice['color']]
        while True:
            font=font_loader(size);bounds=font.getbbox(label);pad=max(4,round(size*.06))
            span=(bounds[2]-bounds[0]+2*pad,bounds[3]-bounds[1]+2*pad)
            if (span[0]<=width*.96 and span[1]<=height*(.87 if len(line['words'])==1 else .45)) or size<=12:break
            size-=2
        sprite=Image.new('RGBA',span);ImageDraw.Draw(sprite).text((pad-bounds[0],pad-bounds[1]),label,font=font,fill=color)
        mask=sprite.getchannel('A');original_width=sprite.width
        boundaries=[0]+[max(0,min(sprite.width,round(pad-bounds[0]+font.getlength(label[:k])))) for k in range(1,len(label))]+[sprite.width]
        sprite=turn(sprite,choice['angle'])
        mask=mask.rotate(choice['angle'],Image.Resampling.BICUBIC,expand=True)
        cosine=math.cos(math.radians(choice['angle']))
        boundaries=[0]+[round(sprite.width/2+(edge-original_width/2)*cosine) for edge in boundaries[1:-1]]+[sprite.width]
        glyph_spans=list(zip(boundaries,boundaries[1:]))
        x=choice['x']*width-sprite.width/2;y=choice['y']*height-sprite.height/2
        words.append(dict(index=index,row=0,x=x,y=y,sprite=sprite,glyph_mask=mask,boxed=False,start=word['start'],
                          length=sprite.width,glyph_spans=glyph_spans,font_size=size))
        if choice['color']=='red':words[-1]['highlight_color']=(239,76,84)
    gap=max(5,base*.12)
    rows=[];row=[];used=0
    for item in words:
        span=item['sprite'].width
        if row and used+gap+span>width:
            rows.append(row);row=[];used=0
        row.append(item);used+=span+(gap if len(row)>1 else 0)
    if row:rows.append(row)
    heights=[max(item['sprite'].height for item in row) for row in rows]
    total=sum(heights)+gap*(len(rows)-1)
    if total>height or any(item['sprite'].width>width for item in words):
        if _fit_depth<24:
            return build_layout(line,choices,scene,width,height,font_loader,font_scale*.93,botanical,_fit_depth+1)
        raise ValueError('This lyric phrase is too long for the reading area; split it into shorter phrases.')
    preferred_top=sum(choice['y'] for choice in choices)/len(choices)*height-total/2
    top=max(0,min(height-total,preferred_top))
    for number,(row,row_height) in enumerate(zip(rows,heights)):
        row_width=sum(item['sprite'].width for item in row)+gap*(len(row)-1)
        x=max(0,min(width-row_width,row[0]['x']))
        for item in row:
            item['x']=x;item['y']=top+(row_height-item['sprite'].height)/2;item['row']=number
            x+=item['sprite'].width+gap
        top+=row_height+gap
    return dict(words=words,size=base,gap=gap)
