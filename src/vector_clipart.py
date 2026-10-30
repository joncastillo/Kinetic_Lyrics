"""Validated model-directed SVG clipart, with a matching transparent PNG for the stage."""

import hashlib
import json
import math
import re
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw


VERSION = 3
SIZE = 256
SCALE = 4
KINDS = ('ellipse', 'circle', 'rect', 'polygon', 'line')
COLOR = re.compile(r'^#[0-9A-Fa-f]{6}$')


def preferred_model(local_json, selected='auto'):
    """Use a smaller installed text model for geometry; keep the selected model as fallback."""
    from gpu_models import normalize, resolve_prompt_model

    installed = {normalize(item.get('name', item.get('model', '')))
                 for item in local_json('tags').get('models', [])}
    for candidate in ('qwen3:14b', 'qwen3:8b', 'qwen3:4b'):
        if normalize(candidate) in installed:
            return candidate
    return resolve_prompt_model(local_json, selected)


def schema(count):
    shape = dict(type='object', properties=dict(
        kind=dict(type='string', enum=list(KINDS)), color=dict(type='string'),
        x=dict(type='number'), y=dict(type='number'), width=dict(type='number'),
        height=dict(type='number'), radius=dict(type='number'),
        cx=dict(type='number'), cy=dict(type='number'), rx=dict(type='number'),
        ry=dict(type='number'), points=dict(type='array', items=dict(type='array',
            items=dict(type='number'), minItems=2, maxItems=2), maxItems=20)),
        required=['kind', 'color'], additionalProperties=False)
    icon = dict(type='object', properties=dict(shapes=dict(type='array', items=shape,
            minItems=3, maxItems=32)), required=['shapes'], additionalProperties=False)
    return dict(type='object', properties=dict(icons=dict(type='array', items=icon,
                minItems=count, maxItems=count)), required=['icons'], additionalProperties=False)


def _number(value, low=-10., high=110.):
    if type(value) not in (int, float) or not low <= value <= high:
        raise ValueError('Vector coordinate is outside its canvas')
    return float(value)


def validate_icon(value):
    if not isinstance(value, dict) or not isinstance(value.get('shapes'), list):
        raise ValueError('Vector model returned no shapes')
    shapes = value['shapes']
    if not 3 <= len(shapes) <= 32:
        raise ValueError('Vector clipart needs 3 to 32 shapes')
    result = []
    for shape in shapes:
        if not isinstance(shape, dict) or shape.get('kind') not in KINDS or not isinstance(shape.get('color'), str) or not COLOR.fullmatch(shape['color']):
            raise ValueError('Unsupported vector shape or colour')
        kind = shape['kind']
        item = dict(kind=kind, color=shape['color'].upper())
        if kind == 'circle':
            item.update(cx=_number(shape.get('cx')), cy=_number(shape.get('cy')),
                        radius=_number(shape.get('radius'), .5, 65.))
        elif kind == 'ellipse':
            item.update(cx=_number(shape.get('cx')), cy=_number(shape.get('cy')),
                        rx=_number(shape.get('rx'), .5, 65.), ry=_number(shape.get('ry'), .5, 65.))
        elif kind == 'rect':
            item.update(x=_number(shape.get('x')), y=_number(shape.get('y')),
                        width=_number(shape.get('width'), .5, 110.),
                        height=_number(shape.get('height'), .5, 110.))
        else:
            points = shape.get('points')
            minimum = 2 if kind == 'line' else 3
            if not isinstance(points, list) or not minimum <= len(points) <= 20:
                raise ValueError('Vector points are missing')
            item['points'] = [(_number(p[0]), _number(p[1])) for p in points
                              if isinstance(p, (list, tuple)) and len(p) == 2]
            if len(item['points']) != len(points):
                raise ValueError('Invalid vector point')
        result.append(item)
    return result


def familiar_icon(subject):
    """Keep common tiny silhouettes legible when a text model cannot place shapes well."""
    name = re.sub(r'[^a-z ]', ' ', subject.lower()).split()
    kind = next((word for word in name if word in {
        'moth', 'butterfly', 'flower', 'blossom', 'heart', 'star', 'leaf',
        'plane', 'airplane', 'jet', 'comet', 'ball', 'moon', 'bird'}), None)
    if kind is None:
        return None
    def polygon(points, color):
        return dict(kind='polygon', points=points, color=color)
    def ellipse(cx, cy, rx, ry, color):
        return dict(kind='ellipse', cx=cx, cy=cy, rx=rx, ry=ry, color=color)
    def circle(cx, cy, radius, color):
        return dict(kind='circle', cx=cx, cy=cy, radius=radius, color=color)
    def line(points, color):
        return dict(kind='line', points=points, color=color)
    if kind in ('moth', 'butterfly'):
        wing = '#EACBA2' if kind == 'moth' else '#F490B6'
        return [polygon([[49,45],[27,16],[10,20],[15,44],[43,57]], wing),
                polygon([[51,45],[73,16],[90,20],[85,44],[57,57]], wing),
                polygon([[45,54],[23,51],[19,77],[40,72],[50,58]], '#D9A16F'),
                polygon([[55,54],[77,51],[81,77],[60,72],[50,58]], '#D9A16F'),
                circle(27,34,5,'#FFF1CE'), circle(73,34,5,'#FFF1CE'),
                ellipse(50,52,5,23,'#30283A'), circle(50,30,6,'#30283A'),
                line([[47,27],[40,13]],'#30283A'), line([[53,27],[60,13]],'#30283A')]
    if kind in ('plane', 'airplane', 'jet'):
        body = '#DCE9F2' if kind != 'jet' else '#9AB8CF'
        return [polygon([[50,7],[55,26],[58,53],[88,68],[88,75],[57,68],[55,82],
                         [68,89],[68,94],[50,89],[32,94],[32,89],[45,82],[43,68],
                         [12,75],[12,68],[42,53],[45,26]], body),
                polygon([[50,12],[54,36],[50,46],[46,36]],'#3A6C91'),
                polygon([[18,69],[42,58],[43,64],[18,75]],'#A0C4D9'),
                polygon([[82,69],[58,58],[57,64],[82,75]],'#A0C4D9')]
    if kind in ('flower', 'blossom'):
        petals=[]
        for i in range(7):
            angle=2*math.pi*i/7
            radial=lambda r, offset=0: [50+math.cos(angle+offset)*r, 50+math.sin(angle+offset)*r]
            petals.append(polygon([radial(7,-.38),radial(35,-.25),radial(41),
                                   radial(35,.25),radial(7,.38)], '#F9A0B7' if i%2 else '#F7C2CD'))
        return petals+[circle(50,50,13,'#F5C954'),circle(46,47,2,'#FFE9A8'),circle(54,53,2,'#FFE9A8')]
    if kind == 'heart':
        points=[]
        for i in range(64):
            t=2*math.pi*i/64
            points.append([50+2.1*16*math.sin(t)**3,
                           47-2.1*(13*math.cos(t)-5*math.cos(2*t)-2*math.cos(3*t)-math.cos(4*t))])
        return [polygon(points,'#EE5C83'),ellipse(37,36,9,5,'#FF9BB1'),circle(29,36,2,'#FFF0F3')]
    if kind == 'star':
        points=[]
        for i in range(10):
            angle=-math.pi/2+i*math.pi/5
            radius=41 if i%2==0 else 18
            points.append([50+radius*math.cos(angle),50+radius*math.sin(angle)])
        return [polygon(points,'#F8CB57'),polygon([[47,14],[51,14],[43,44],[38,46]],'#FFECA3'),
                circle(50,51,4,'#FFE294')]
    if kind == 'leaf':
        return [polygon([[15,80],[24,39],[52,12],[88,15],[80,54],[49,82]],'#6BC685'),
                polygon([[15,80],[42,62],[81,25],[69,61],[49,82]],'#3A9C67'),
                line([[15,82],[47,56],[75,27]],'#DBF4A9')]
    if kind == 'comet':
        return [polygon([[19,91],[34,56],[55,35],[69,41]],'#54A9DF'),
                polygon([[8,76],[43,47],[61,38],[70,44]],'#9CE5F0'),
                circle(71,32,19,'#F7D77D'),circle(67,27,8,'#FFF4BB')]
    if kind in ('ball', 'moon'):
        return [circle(50,50,37,'#E9EEF2' if kind=='moon' else '#F4A661'),
                ellipse(40,37,15,8,'#FFFFFF'),
                circle(66,58,5,'#C3D1DF' if kind=='moon' else '#DD784E')]
    return [polygon([[49,46],[22,26],[11,41],[38,61]],'#72B8D6'),
            polygon([[51,46],[78,26],[89,41],[62,61]],'#72B8D6'),
            ellipse(50,57,8,24,'#39475A'),polygon([[49,39],[50,25],[58,37]],'#E9B76E'),
            line([[48,79],[43,86]],'#39475A'),line([[52,79],[57,86]],'#39475A')]


def render_icon(shapes, size=SIZE):
    big = size*SCALE
    image = Image.new('RGBA', (big, big))
    draw = ImageDraw.Draw(image)
    s = big/100
    for shape in shapes:
        color = shape['color']
        kind = shape['kind']
        if kind == 'circle':
            x, y, r = shape['cx']*s, shape['cy']*s, shape['radius']*s
            draw.ellipse((x-r, y-r, x+r, y+r), fill=color)
        elif kind == 'ellipse':
            x, y, rx, ry = shape['cx']*s, shape['cy']*s, shape['rx']*s, shape['ry']*s
            draw.ellipse((x-rx, y-ry, x+rx, y+ry), fill=color)
        elif kind == 'rect':
            x, y = shape['x']*s, shape['y']*s
            draw.rectangle((x, y, x+shape['width']*s, y+shape['height']*s), fill=color)
        elif kind == 'polygon':
            draw.polygon([(x*s, y*s) for x, y in shape['points']], fill=color)
        else:
            draw.line([(x*s, y*s) for x, y in shape['points']], fill=color,
                      width=max(2, round(s*1.2)), joint='curve')
    return image.resize((size, size), Image.Resampling.LANCZOS)


def svg_text(shapes):
    root = ET.Element('svg', xmlns='http://www.w3.org/2000/svg', viewBox='0 0 100 100',
                      width='100', height='100')
    for shape in shapes:
        kind = shape['kind']
        attributes = {'fill': shape['color']}
        if kind == 'circle':
            attributes.update(cx=str(shape['cx']), cy=str(shape['cy']), r=str(shape['radius']))
        elif kind == 'ellipse':
            attributes.update(cx=str(shape['cx']), cy=str(shape['cy']),
                              rx=str(shape['rx']), ry=str(shape['ry']))
        elif kind == 'rect':
            attributes.update(x=str(shape['x']), y=str(shape['y']),
                              width=str(shape['width']), height=str(shape['height']))
        else:
            attributes['points'] = ' '.join(f'{x:g},{y:g}' for x, y in shape['points'])
            if kind == 'line':
                kind = 'polyline'
                attributes.update(fill='none', stroke=shape['color'], **{'stroke-width': '1.2', 'stroke-linecap': 'round'})
        ET.SubElement(root, kind, attributes)
    return ET.tostring(root, encoding='unicode')


def request_icons(prompts, subjects, model, request):
    payload = dict(model=model, think=False, stream=False, keep_alive=0,
                   format=schema(len(subjects)), options=dict(num_ctx=8192,
                   num_predict=max(1800, len(subjects)*1800), temperature=.25),
                   messages=[dict(role='system', content=(
                       'Design polished, minimal SVG clipart as JSON geometry on a transparent 100 by 100 canvas. '
                       'Use only circles, ellipses, rectangles, polygons and short line details. Return 5 to 20 shapes '
                       'per icon, layered back to front. Design the recognizable silhouette of the specific named subject '
                       'before adding ornament. Every icon must be immediately identifiable at 64 pixels. '
                       'For winged insects, draw broad separate LEFT and RIGHT wings spanning x 12..88, a narrow vertical '
                       'center body and antennae; never stack circles or wings vertically. For aircraft, draw a long fuselage '
                       'with two clear side wings and tail. For flowers, show separate radial petals around a center. '
                       'Center the subject within x/y 10..90, filling most of that area. '
                       'Use solid six-digit hex colours and no background shape, text, gradients, filters, shadows, '
                       'external assets or white sticker outline. Keep colours harmonious with the requested accent. '
                       'Coordinates are in 0..100. For circle use cx,cy,radius; ellipse cx,cy,rx,ry; '
                       'rect x,y,width,height; polygon or line points [[x,y],...].')),
                       dict(role='user', content=json.dumps([
                           dict(subject=subject, brief=prompt[:1100]) for subject, prompt in zip(subjects, prompts)
                       ], ensure_ascii=False))])
    answer = request('chat', payload, timeout=240)
    icons = json.loads(answer.get('message', {}).get('content') or '{}').get('icons')
    if not isinstance(icons, list) or len(icons) != len(subjects):
        raise ValueError('Vector model returned the wrong number of icons')
    return [validate_icon(icon) for icon in icons]


def paint_icons(prompts, subjects, folder, options, kind='video.ornaments', request=None):
    """Cache editable SVGs and transparent PNGs; the raster image model is not loaded."""
    from ollama_service import local_json

    templates = [familiar_icon(subject) for subject in subjects]
    model = (options.get('mini_image_model') or preferred_model(local_json, options.get('ai_model', 'auto'))
             if any(icon is None for icon in templates) else 'built-in-vector')
    signature = dict(version=VERSION, model=model, subjects=subjects, prompts=prompts,
                     seed=options.get('image_seed', 42))
    key = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:20]
    target = Path(folder)/kind/key
    paths = [target/f'{i:03d}.png' for i in range(len(subjects))]
    if all(path.is_file() for path in paths):
        return paths
    target.mkdir(parents=True, exist_ok=True)
    if request is None:
        from ollama_gpu import gpu_chat
        request = gpu_chat
    try:
        missing = [i for i, icon in enumerate(templates) if icon is None]
        icons = templates[:]
        if missing:
            print(f'Drawing {len(missing)} vector clipart picture(s) with {model}...', flush=True)
            generated = request_icons([prompts[i] for i in missing], [subjects[i] for i in missing], model, request)
            for index, shapes in zip(missing, generated):
                icons[index] = shapes
        for index, shapes in enumerate(icons):
            svg = paths[index].with_suffix('.svg')
            svg.write_text(svg_text(shapes), encoding='utf-8')
            render_icon(shapes).save(paths[index])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'Warning: vector clipart unavailable ({exc}); affected picture slots stay empty.', flush=True)
    return [path if path.is_file() else None for path in paths]
