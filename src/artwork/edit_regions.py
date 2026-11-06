"""Numbered Qwen edit guides and optional preservation outside their selected regions."""
import math
from PIL import ImageDraw, ImageFont

MAX_REGIONS = 12
COLOURS = ('#ff375f', '#00bfff', '#ffcc00', '#34c759', '#bf5af2', '#ff9500')


def checked_regions(value, source, names, spec):
    if value in (None, []):
        return []
    if not isinstance(value, list) or len(value) > MAX_REGIONS:
        raise ValueError(f'Choose at most {MAX_REGIONS} edit regions')
    if spec['pipeline'] != 'QwenImage21Pipeline':
        raise ValueError('Multi-region guides currently require Qwen Image 2.1')
    if source not in names:
        raise ValueError('Keep the region guide source in Images sent to the model')
    if len(names)+1 > spec.get('max_references', 4):
        raise ValueError('The region guide uses one reference slot; remove another reference picture')
    result = []
    for region in value:
        try:
            x, y, w, h = (float(region[k]) for k in ('x', 'y', 'w', 'h'))
        except (TypeError, KeyError, ValueError):
            raise ValueError('Invalid edit region coordinates') from None
        if not all(math.isfinite(n) for n in (x,y,w,h)) or min(x,y)<0 or min(w,h)<.002 or x+w>1.000001 or y+h>1.000001:
            raise ValueError('Edit regions must stay inside the source image')
        result.append(dict(x=x,y=y,w=w,h=h,instruction=str(region.get('instruction') or '')[:600]))
    return result


def guide_image(source, regions):
    guide = source.convert('RGB').copy()
    draw = ImageDraw.Draw(guide)
    width, height = guide.size
    line = max(2, round(min(width,height)/180))
    font = ImageFont.load_default(size=max(14, round(min(width,height)/28)))
    for index, r in enumerate(regions):
        box = (round(r['x']*width),round(r['y']*height),min(width-1,round((r['x']+r['w'])*width)),min(height-1,round((r['y']+r['h'])*height)))
        colour = COLOURS[index % len(COLOURS)]
        draw.rectangle(box, outline=colour, width=line)
        label=str(index+1); bounds=draw.textbbox((0,0),label,font=font)
        x,y=box[:2]; label_width=bounds[2]-bounds[0]+8; label_height=bounds[3]-bounds[1]+8
        x=min(x,max(0,width-label_width)); y=min(y,max(0,height-label_height))
        draw.rectangle((x,y,x+label_width,y+label_height),fill=colour)
        draw.text((x+4,y+4-bounds[1]),label,font=font,fill='black')
    return guide


def guide_prompt(prompt, regions, source_number, guide_number):
    details=' '.join(f'Region {i+1}: {r["instruction"]}.' for i,r in enumerate(regions) if r.get('instruction'))
    return (f'Reference image {source_number} is the clean image to edit. Reference image {guide_number} is the same '
            f'image with {len(regions)} numbered coloured rectangles marking the requested edit regions. Apply the '
            'following changes inside those rectangles. Preserve the composition, identity and appearance outside '
            'them as closely as possible. The rectangles and numbers are instructions only: remove all guide markings '
            'from the output. Other reference images supply the requested identity or visual details. '
            +prompt+' '+details)


def preserve_outside_regions(source, generated, regions):
    """Keep source pixels outside the union of the rectangles, at source resolution.

    Feather only inward. The generation model may still change the whole image;
    this composition discards every change outside the user's selection.
    """
    from PIL import Image, ImageChops
    if not regions:
        raise ValueError('Choose at least one region to preserve the rest of the source image.')
    base = source.convert('RGBA' if 'A' in source.getbands() or 'transparency' in source.info else 'RGB')
    edited = generated.convert(base.mode).resize(base.size, Image.Resampling.LANCZOS)
    mask = Image.new('L', base.size)
    width, height = base.size
    for region in regions:
        left, top = round(region['x']*width), round(region['y']*height)
        right = min(width, round((region['x']+region['w'])*width))
        bottom = min(height, round((region['y']+region['h'])*height))
        if right <= left or bottom <= top:
            raise ValueError('The selected region is smaller than one source pixel.')
        patch = Image.new('L', (right-left, bottom-top))
        draw = ImageDraw.Draw(patch)
        feather = min(max(1, round(min(patch.size)*.12)), 16, (min(patch.size)-1)//2)
        for inset in range(feather+1):
            alpha = round(255*(.5-.5*math.cos(math.pi*inset/feather))) if feather else 255
            draw.rectangle((inset, inset, patch.width-1-inset, patch.height-1-inset), fill=alpha)
        existing = mask.crop((left, top, right, bottom))
        mask.paste(ImageChops.lighter(existing, patch), (left, top))
    return Image.composite(edited, base, mask)


def region_context(source, region):
    """A close-up with context around the edit and its rectangle in crop coordinates."""
    width, height = source.size
    left, top = round(region['x']*width), round(region['y']*height)
    right, bottom = round((region['x']+region['w'])*width), round((region['y']+region['h'])*height)
    span = max(256, 3*max(right-left, bottom-top))
    crop_width, crop_height = min(width, span), min(height, span)
    x = max(0, min(width-crop_width, (left+right-crop_width)//2))
    y = max(0, min(height-crop_height, (top+bottom-crop_height)//2))
    crop = source.crop((x, y, x+crop_width, y+crop_height))
    local = dict(region, x=(left-x)/crop_width, y=(top-y)/crop_height,
                 w=(right-left)/crop_width, h=(bottom-top)/crop_height)
    return crop, (x, y), local
