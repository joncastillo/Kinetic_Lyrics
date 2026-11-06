"""The kinetic-type styles. Each takes progress p (0 -> 1) and draws the word's letters at that pose.

While letters move they are drawn as their flat bodies (crisp) so copies, extrusions and badges read like print;
the real sprite column, with its soft shadow, fades back in for the last moments so the final frame is exact.
"""
import math

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from effects.kinetic import staggered, stretch, style
from effects.kinetic.easing import (back_out, circ_in_out, clamp, keyframes, pulse, smooth, smoother,
                                    window)
from effects.kinetic.glyphs import (saturation, accent_palette, bright_accent, colored, contrast_accent, crisp, darker, draw_glyph,
                                    far_fills, faded, ink_color, luminance, safe_paste, shade_color, solid_only, warm_fill)


def varied_accent(ink, rng, seed=None):
    """A loud accent that contrasts with the word; with a seed, consecutive words step through the options so
    neighbours never share a colour."""
    from effects.kinetic.glyphs import luminance as lum
    deep = ((90, 50, 230), (210, 20, 70), (12, 120, 110), (230, 70, 10), (170, 20, 140))
    bright = ((198, 255, 26), (255, 196, 40), (90, 230, 210), (255, 150, 200), (255, 120, 60))
    options = [c for c in (deep if lum(ink) > .5 else bright) if sum((a-b)**2 for a, b in zip(c, ink[:3])) > 9000]
    return options[seed % len(options)] if seed is not None else rng.choice(options)


FILL_CYCLE = ((238, 46, 72), (16, 168, 150), (122, 92, 255), (255, 96, 28), (226, 40, 150))


def bounds(pieces):
    return (min(g.left+g.ink_left for g in pieces), min(g.top for g in pieces),
            max(g.left+g.ink_right for g in pieces), max(g.bottom for g in pieces))


def outlined(image, color, edge, width):
    """`image`'s body filled flat with `color` inside a hard `edge`-coloured outline `width` px thick."""
    body = solid_only(image).getchannel('A')
    grown = body.filter(ImageFilter.MaxFilter(width*2+1)) if width > 0 else body
    out = Image.new('RGBA', image.size, (*edge, 0))
    out.putalpha(grown)
    fill = Image.new('RGBA', image.size, (*color, 0))
    fill.putalpha(body)
    out.alpha_composite(fill)
    return out


def scaled_about(layer, image, x, y, cx, cy, scale):
    """Paste sprite-sized `image` (top-left at x, y) scaled by `scale` about the sprite point (cx, cy)."""
    if abs(scale-1) < .002:
        safe_paste(layer, image, x, y)
        return
    big = stretch(image, scale, scale)
    safe_paste(layer, big, x+cx-cx*big.width/image.width, y+cy-cy*big.height/image.height)


# 1. Elastic stretch ---------------------------------------------------------------------------------------------
STRETCH_POSES = [(0., (.85, .7)), (.22, (.52, 1.6)), (.4, (1.42, .7)), (.47, (1.42, .7)), (.7, (.93, 1.08)),
                 (.86, (1.02, .98)), (1., (1., 1.))]


@style('elastic-stretch')
def elastic_stretch(layer, sprite, x, y, p, effect, pieces, rng, intensity, seed=0):
    """Letter by letter, each one shoots up tall and thin in a hot accent over an offset print plate, slams down
    short and wide (turning the word's own colour on the impact), springs back and locks."""
    ink = ink_color(sprite)
    accent = warm_fill(rng)
    plate = (70, 40, 220) if luminance(ink) > .6 and saturation(ink) > .25 else darker(accent, .55)
    height = max(g.height for g in pieces)
    count = len(pieces)
    amount = .6+.4*min(1.5, intensity)
    if any(g.height < height*.8 for g in pieces):  # lowercase: a gentler stretch so ascenders never pile up
        amount *= .6
    for index, glyph in enumerate(pieces):
        q = clamp((p-.22*index/max(1, count-1))/.43) if count > 1 else clamp(p/.6)
        if q <= 0:
            continue
        sx, sy = keyframes(q, STRETCH_POSES)
        if (seed+(index//2 if count > 5 else 0)) % 2 and q < .7:  # alternate words (and letter pairs in long words) lead squat and wide
            sx, sy = sy, sx
        sx, sy = 1+(sx-1)*amount, 1+(sy-1)*amount
        if glyph.height > height*.85 and sy > 1:  # ascenders and capitals stretch less, so they stay off their neighbours
            sy = 1+(sy-1)*.6
        lag = .14*(index//2)/max(1, (count-1)//2)
        flash = pulse(window(p, .55+lag, .7+lag))  # late, two letters at a time: a flash of the accent
        thump = .06*flash  # over a small squash (a big one flickers)
        sx, sy = sx*(1+thump), sy*(1-thump)
        hot = q < .4 or flash > .3  # the squashing letter flashes the accent
        body = crisp(glyph.image, q)
        image = colored(body, accent) if hot else body
        late = (1+.1*index/max(1, count-1))*(.55 if any(g.height < height*.8 for g in pieces) else 1.)
        spread = (index-(count-1)/2)*(height*.07*pulse(window(p, .05, .55))+glyph.width*.3*max(0., sx-1))*late
        # A misregistered flat plate behind the letter, like a two-colour print, sliding home as it locks.
        offset = height*.07*min(1.4, intensity)*(1-smoother(window(q, .55, .9)))*(.55 if glyph.height < height*.8 else 1.)
        if offset > .5:
            draw_glyph(layer, glyph, x, y, sx, sy, dx=offset+spread, dy=offset, image=colored(solid_only(glyph.image), plate))
        draw_glyph(layer, glyph, x, y, sx, sy, dx=spread, image=image)


# 2. Echo cascade -------------------------------------------------------------------------------------------------
@style('echo-cascade')
def echo_cascade(layer, sprite, x, y, p, effect, pieces, rng, intensity):
    """Each letter drops in on a staircase of hard, outlined colour copies, stepping higher letter by letter
    like a printed rainbow; the copies fold down into it front first, the letter plunges through the baseline,
    squashes, springs back and locks."""
    ink = ink_color(sprite)
    hue = (255, 92, 40) if luminance(ink) > .6 else (226, 40, 150)
    palette = [tuple(min(255, round(c+(255-c)*.35)) for c in hue), hue, darker(hue, .45)]
    edge = shade_color(ink)
    count = len(pieces)
    height = max(g.height for g in pieces)
    step = height*.2*min(1.3, intensity)
    width = 0
    for index, glyph in enumerate(pieces):
        q = staggered(p, index, count, effect.stagger)
        if q <= 0:
            continue
        lift = .6+.4*(.5+.5*math.sin(index*1.25+.6))
        drop = (1-smooth(window(q, 0, .32)))*height*.3
        dip = 0.
        squash = 1+.22*dip
        body = crisp(glyph.image, q)
        for k in range(len(palette), 0, -1):
            fold = circ_in_out(window(q, .14+.06*(k-1), .38+.08*k))
            rise = step*k*lift*(1-fold)*glyph.height/height*(1-smoother(window(p, .32, .54)))  # every copy is home by 0.54
            if rise < .6:
                continue
            press = .2*pulse(window(fold, .6, 1.)) if k == 1 else -.16*pulse(window(q, .08, .4)) if k == len(palette) else 0.
            fan = (1 if index % 2 else -1)*5*k*(1-smoother(window(fold, 0, .5)))*smoother(window(q, 0, .16))  # opens as it arrives, closes onto the baseline  # one fan about the letter's baseline
            swing = math.radians(fan)
            draw_glyph(layer, glyph, x, y, 1+press*.6, 1-press, angle=fan, dx=-rise*math.sin(swing), dy=-rise*math.cos(swing)-drop,
                       image=outlined(glyph.image, palette[k-1], edge, width))
        draw_glyph(layer, glyph, x, y, squash**.5, 1/squash, dy=-drop+dip*height*.05, image=body)


# 3. Echo jump ----------------------------------------------------------------------------------------------------
def leaping_letters(pieces):
    """Round letters near the middle first, then the rest by distance from the middle."""
    count = len(pieces)
    middle = (count-1)/2
    return sorted(range(count), key=lambda i: (pieces[i].roundness <= .35, abs(i-middle)))


@style('echo-chain')
def echo_chain(layer, sprite, x, y, p, effect, pieces, rng, intensity, seed=0):
    """The word snaps together letter by letter while a bright twin of one letter crouches and springs up and
    out of it on a diagonal, leaving a fan of full-size coloured echoes stepping back down to the word, then
    drops back, squashes and locks into its letter; a second letter answers with a smaller jump the other way."""
    count = len(pieces)
    order = leaping_letters(pieces)
    leapers = order[:1]
    palette = accent_palette(rng, 4, fills=True)
    height = max(g.height for g in pieces)
    reach = min(1.4, intensity)
    jumps, landing = [], {}
    for rank, index in enumerate(leapers):
        glyph = pieces[index]
        start = .2+.2*rank  # only once the word around it has built
        q = clamp((p-start)/(.8-start))
        if q <= 0 or q >= .9:
            continue
        side = (1 if index >= (count-1)/2 else -1)*(1 if rank == 0 else -1)
        top = height*(1.12 if rank == 0 else .8)*reach
        rise = keyframes(q, [(0, 0.), (.1, -.08), (.42, 1.), (.52, 1.), (.8, -.04), (.9, 0.)], ease=circ_in_out)
        lift = top*max(0., rise)
        drift = top*.75*((seed % 3)-1)*smoother(window(rise, .4, 1.))  # straight up, or arcing left or right
        echoes = smoother(window(q, .12, .36))*(1-smoother(window(q, .55, .82)))
        if echoes > .01:
            links = 2
            for k in range(links, 0, -1):
                share = k/(links+1)
                scale = .9**k
                draw_glyph(layer, glyph, x, y, scale, scale, dx=drift*(1-share)*echoes**.3+side*glyph.width*.12*k,
                           dy=-lift*(1-share)*echoes**.3, anchor='middle',
                           image=colored(solid_only(glyph.image), tuple(round(c*(1-.22*k)+255*.12*k) for c in palette[(2*rank) % len(palette)])))
        crouch = pulse(window(q, 0, .16))*.24
        land = pulse(window(q, .76, .9))*.28
        squash = (1-crouch)/(1+land)
        twin = colored(solid_only(glyph.image), palette[(2*rank) % len(palette)])
        warm = smooth(window(q, 0, .2))  # the twin warms from the letter's own ink into its accent
        image = twin if warm >= 1 else Image.blend(crisp(glyph.image, 0.), twin, warm)
        tilt = 0.
        if rise <= 0 and q > .5:  # back home: the letter itself takes the landing squash
            landing[index] = squash
            continue
        jumps.append((glyph, squash, drift, lift, tilt, image))
    for index, glyph in enumerate(pieces):
        q = clamp((p-.06*index/max(1, count-1))/.4)
        if q <= 0:
            continue
        land = smooth(q)
        squash = landing.get(index, 1.)
        draw_glyph(layer, glyph, x, y, (.7+.3*land)/max(.9, squash)**1.5, (.7+.3*land)*max(.9, squash), image=crisp(glyph.image, clamp((p-.6)/.4)))
    for glyph, squash, drift, lift, tilt, image in jumps:  # the jumping twins fly in front of the word
        draw_glyph(layer, glyph, x, y, 1/squash**.5, squash, dx=drift, dy=-lift, angle=tilt, image=image)


# 4. Pop extrude --------------------------------------------------------------------------------------------------
@style('pop-extrude')
def pop_extrude(layer, sprite, x, y, p, effect, pieces, rng, intensity, seed=0):
    """A chunky badge slams open past full size and settles; letters spring up off it fanned out on deep,
    tapered 3D extrusions in the badge's own dark shade, squash hard as they seat, stand straight, and the
    badge snaps shut."""
    ink = ink_color(sprite)
    badge = (96, 24, 72) if luminance(ink) > .6 and saturation(ink) > .25 else varied_accent(ink, rng, seed)
    near, far = darker(badge, .5), darker(badge, .82)
    count = len(pieces)
    height = max(g.height for g in pieces)
    left, top, right, base = bounds(pieces)
    open_ = keyframes(p, [(0, .4), (.2, 1.2), (.25, 1.2), (.32, .95), (.4, 1.), (.56, 1.), (.66, 0.)])
    tilt = 5*pulse(window(p, .14, .34))*(1 if rng.random() < .5 else -1)
    if open_ > .01:
        target = layer
        layer = Image.new('RGBA', target.size)
        draw = ImageDraw.Draw(layer)
        pad = height*.22
        width = (right-left+pad*2)*(.25+.75*open_)
        tall = ((base-top)*.62+height*.06)*open_
        cx, bottom = x+(left+right)/2, y+base+height*.12*open_
        box = (cx-width/2, bottom-tall, cx+width/2, bottom)
        off = height*.08*open_
        radius = max(1., min(height*.12, tall/2))
        draw.rounded_rectangle((box[0]+off, box[1]+off, box[2]+off, box[3]+off), radius=radius, fill=(*far, 255))
        draw.rounded_rectangle(box, radius=radius, fill=(*badge, 255))
        if abs(tilt) > .05:  # the badge lands at a slight angle and rocks level
            layer = layer.rotate(tilt, Image.Resampling.BICUBIC, center=(cx, bottom))
        target.alpha_composite(layer)
        layer = target
    middle = (count-1)/2
    for index, glyph in enumerate(pieces):
        q = staggered(p, index, count, effect.stagger)
        if q <= 0:
            continue
        rise = keyframes(q, [(0, .7), (.24, 1.12), (.38, 1.), (1., 1.)])
        if index == 0:  # the lead letter trades proportions: squat and heavy, then tall, then home
            swap_x, swap_y = keyframes(q, [(0, (1., 1.)), (.22, (1.55, .62)), (.34, (1.55, .62)), (.46, (.74, 1.4)), (.58, (.74, 1.4)), (.74, (1., 1.)), (1., (1., 1.))])
        elif index == 1 and count > 2:  # the next letter echoes the trade, smaller and a beat later
            sx2, sy2 = keyframes(clamp(q-.1), [(0, (1., 1.)), (.2, (1.36, .72)), (.36, (1.36, .72)), (.48, (.8, 1.3)), (.62, (.8, 1.3)), (.76, (1., 1.)), (1., (1., 1.))])
            swap_x, swap_y = sx2, sy2
        else:
            swap_x = swap_y = 1.
        seat = pulse(window(q, .42, .66))
        flat = .05*pulse(window(p, .68, .8))  # one last flatten as the slab goes
        sx, sy = (1+.12*seat)*swap_x*(1+flat), rise*(1-.16*seat)*swap_y*(1-flat)
        fan = (index-middle)/max(1, middle) if count > 1 else 0
        lean = fan*16*min(1.4, intensity)*(1-smoother(window(q, .3, .8)))
        relay = .24+.22*index/max(1, count-1)  # the depth surge runs along the word, left to right
        surge = 1+.9*pulse(window(p, relay, relay+.11))
        body_depth = max(pulse(window(q, 0, .68))**.55, .3 if q > .3 else 0.)  # a thin slab stays until the lock
        depth = height*.38*min(1.4, intensity)*body_depth*surge*(1-smoother(window(p, .72, .82)))
        face = crisp(glyph.image, q)
        if q < .84:  # a lit rim along the top-left of the face, like the bevel on a sign letter
            rim = Image.new('RGBA', face.size)
            kiss = min(1., max(0., surge-1.45)/.35)  # at the surge's peak the rim flares in the badge's own colour
            lit = tuple(min(255, round(c+90*(1-kiss)+(c*.35+60)*kiss)) for c in badge)
            edge = max(1, round(height*(.025+.03*kiss)))
            rim.alpha_composite(colored(solid_only(face), lit), (-edge, -edge))
            rim.alpha_composite(face)
            face = rim
        draw_glyph(layer, glyph, x, y, sx, sy, angle=-lean, image=face,
                   extrude=(depth, math.radians(58-lean*1.4), near, far, .22))


# 5. Bar wipe -----------------------------------------------------------------------------------------------------
@style('scan-slice')
def scan_slice(layer, sprite, x, y, p, effect, pieces, rng, intensity, seed=0):
    """The word is cut into three thick slabs. Solid colour bars shoot in from alternate sides, each carrying
    its slab of lettering printed dark inside it; the slabs slam into register, each bar snaps shut to nothing
    in a couple of frames (the lettering switching to its own colour as it goes), and the word punches in."""
    left, top, right, bottom = bounds(pieces)
    count = 2
    edges = [round(top+(bottom-top)*k/count) for k in range(count+1)]
    edges[0], edges[-1] = 0, sprite.height
    colors = [FILL_CYCLE[(seed+k*2) % len(FILL_CYCLE)] for k in range(count)]
    reach = min((right-left)*.18, (bottom-top)*.8)*min(1.4, intensity)
    pad = (bottom-top)*.1
    draw = ImageDraw.Draw(layer)
    punch = 1+.08*pulse(window(p, .56, .8))
    scene = Image.new('RGBA', sprite.size)
    for k in range(count):
        a, b = edges[k], edges[k+1]
        q = clamp((p-.015*k)/.4)
        if q <= 0:
            continue
        direction = (-1 if k % 2 else 1)*(-1 if seed % 3 == 1 else 1)
        travel = back_out(q, 1.2)
        dx = direction*(1-travel)*reach+direction*(right-left)*.045*smooth(pulse(window(p, .4, .56)))
        slab = sprite.crop((0, a, sprite.width, b))
        thick = 1-smoother(window(p, .44+.05*k, .6+.05*k))
        if thick > .3:
            bar_top = top-pad if k == 0 else a
            bar_bottom = bottom+pad if k == count-1 else b
            mid, half = (bar_top+bar_bottom)/2, (bar_bottom-bar_top)/2*thick
            trail = max(0., 1-travel)*reach*.8
            flare = (right-left)*.05*pulse(window(p, .3, .5))
            box = (x+left-pad-flare+dx-(trail if direction > 0 else 0), y+mid-half,
                   x+right+pad+flare+dx+(trail if direction < 0 else 0), y+mid+half)
            wipe = smoother(window(q, 0, .45))  # each bar wipes in from its leading edge, full height at once
            if direction > 0:
                box = (box[0], box[1], box[0]+(box[2]-box[0])*wipe, box[3])
            else:
                box = (box[2]-(box[2]-box[0])*wipe, box[1], box[2], box[3])
            draw.rectangle(box, fill=(*colors[k], 255))
        # The dark print gives way to the word's own ink along a sweep across the word, not in one cut.
        sweep = smoother(window(p, .38+.04*k, .54+.04*k))
        dark = colored(solid_only(slab), shade_color(colors[k]))
        if sweep <= 0:
            body = dark
        else:
            body = crisp(slab, clamp((p-.62)/.38*.18+.82))
            if sweep < 1:
                cut = round(slab.width*sweep) if direction > 0 else round(slab.width*(1-sweep))
                region = (cut, 0, slab.width, slab.height) if direction > 0 else (0, 0, cut, slab.height)
                body = body.copy()
                body.paste(dark.crop(region), region[:2])
        lean = direction*.18*smooth(pulse(window(p, .34, .56)))  # about 10 degrees of shear, then upright
        if abs(lean) > .002:
            body = body.transform(body.size, Image.Transform.AFFINE, (1, lean, -lean*body.height/2, 0, 1, 0), Image.Resampling.BICUBIC)
        wipe = smoother(window(q, .08, .5))
        if wipe < .999:  # the lettering is carried inside the wiping bar, whole letters only
            reach = body.width*wipe if direction > 0 else body.width*(1-wipe)
            stops = [g.left for g in pieces]+[sprite.width]
            cut = max([s for s in stops if s <= reach] or [0]) if direction > 0 else min([s for s in stops if s >= reach] or [sprite.width])
            shown = cut if direction > 0 else body.width-cut
            body = body.crop((0, 0, max(1, shown), body.height)) if direction > 0 else body.crop((body.width-max(1, shown), 0, body.width, body.height))
            safe_paste(scene, body, dx+(0 if direction > 0 else sprite.width-body.width), a)
        else:
            safe_paste(scene, body, dx, a)
    if p < .6:  # hold back letters that any bar has not yet covered
        allowed = Image.new('L', sprite.size)
        gate = ImageDraw.Draw(allowed)
        margin = 1
        for glyph in pieces:
            ok = True
            for k in range(count):
                q = clamp((p-.015*k)/.4)
                wipe = smoother(window(q, .08, .5))
                direction = (-1 if k % 2 else 1)*(-1 if seed % 3 == 1 else 1)
                edge = sprite.width*wipe if direction > 0 else sprite.width*(1-wipe)
                if (direction > 0 and glyph.right > edge+1) or (direction < 0 and glyph.left < edge-1):
                    ok = False
            if ok:
                gate.rectangle((glyph.left-margin, 0, glyph.right+margin, sprite.height), fill=255)
        scene.putalpha(Image.fromarray(np.minimum(np.asarray(scene.getchannel('A')), np.asarray(allowed))))
    scaled_about(layer, scene, x, y, (left+right)/2, (top+bottom)/2, punch)


# 6. Page peel ----------------------------------------------------------------------------------------------------
@style('page-peel')
def page_peel(layer, sprite, x, y, p, effect, pieces, rng, intensity, seed=0):
    """A loud blank sticker slams down with a twist, then peels away from one corner, its curled
    back shaded along the fold; the letters underneath, squashed flat by the sticker, spring up one by one as
    the fold passes them, and the flap flicks off."""
    sheet_color = bright_accent(rng)
    back_color = (244, 236, 216)  # the sticker's paper back, flat cream
    left, top, right, bottom = bounds(pieces)
    margin = (bottom-top)*.24
    box = (left-margin, top-margin, right+margin, bottom+margin)
    pad = round(max(box[2]-box[0], box[3]-box[1])*.25)
    size = (sprite.width+pad*2, sprite.height+pad*2)
    box = tuple(v+pad for v in box)
    slap = window(p, 0, .26)
    peel = smooth(window(p, .08, .6))
    sheet = Image.new('RGBA', size)
    ImageDraw.Draw(sheet).rounded_rectangle(box, radius=margin*.7, fill=(*sheet_color, 255))
    # The word is ghost-printed on the sticker, tone on tone; it comes to life as the sticker comes away.
    sheet.alpha_composite(colored(solid_only(sprite), darker(sheet_color, .22)), (pad, pad))
    corner = np.array((box[2], box[3]) if seed % 2 == 0 else (box[0], box[3]), float)
    far = np.array((box[0], box[1]) if seed % 2 == 0 else (box[2], box[1]), float)
    diagonal = far-corner
    length = float(np.hypot(*diagonal))
    normal = diagonal/length
    point = corner+normal*(peel*length*1.3)
    gy, gx = np.mgrid[0:size[1], 0:size[0]]
    side = (gx-point[0])*normal[0]+(gy-point[1])*normal[1]
    stuck = Image.fromarray(((side > 0)*255).astype('uint8'), 'L')
    peeled = Image.fromarray(((side <= 0)*255).astype('uint8'), 'L')
    remaining = Image.new('RGBA', size)
    remaining.paste(sheet, mask=stuck)
    loose = Image.new('L', size)
    loose.paste(sheet.getchannel('A'), mask=peeled)
    a, b = normal
    c = -(a*point[0]+b*point[1])
    flap_alpha = loose.transform(size, Image.Transform.AFFINE, (1-2*a*a, -2*a*b, -2*a*c, -2*a*b, 1-2*b*b, -2*b*c),
                                 Image.Resampling.BILINEAR)
    flick = 1-smoother(window(p, .54, .64))
    if flick < .999:
        flap_alpha = flap_alpha.point(lambda v: round(v*flick))
    curl = np.clip(np.abs(side)/max(1., (box[3]-box[1])*.8), 0, 1)
    back = np.zeros((size[1], size[0], 4), np.float32)
    back[..., :3] = np.where(curl[..., None] < .45, np.array(back_color, np.float32), np.array(darker(sheet_color, .3), np.float32))  # two flat print tones
    back[..., 3] = np.asarray(flap_alpha, np.float32)
    flap = Image.fromarray(back.clip(0, 255).astype('uint8'), 'RGBA')
    shadow = Image.new('RGBA', size)
    shadow.putalpha(flap_alpha.filter(ImageFilter.GaussianBlur(max(1, margin*.5))).point(lambda v: round(v*.4)))
    cover = Image.new('RGBA', size)
    cover.alpha_composite(remaining)
    cover.alpha_composite(shadow, (round(margin*.15), round(margin*.25)))
    cover.alpha_composite(flap)
    # Letters under the sheet spring up from flat as the fold line passes over them.
    for glyph in pieces:
        centre = np.array((glyph.left+(glyph.ink_left+glyph.ink_right)/2+pad, glyph.middle+pad))
        passed = float((centre-corner)@normal)/(length*1.3)
        hop = clamp((peel-passed-.02)/.45)
        if hop <= .04:
            continue
        sy = keyframes(hop, [(.04, 1.), (.22, 1.), (.4, 1.08), (.6, .97), (1, 1.)])
        jump = (bottom-top)*.08*pulse(window(hop, .15, .7))
        grow = .45+.55*back_out(smoother(window(hop, .04, .3)), 1.4)  # each letter springs up from small, not all at once
        draw_glyph(layer, glyph, x, y, grow/max(.6, sy)**.4, sy*grow, dy=-jump, image=crisp(glyph.image, clamp(p/.95)))
    if slap < 1:
        scale = .5+.5*back_out(smooth(slap), 2.2)
        cover = stretch(cover, scale, scale)
        cover = cover.rotate(-14*(1-slap)**2, Image.Resampling.BICUBIC, expand=True)
        if slap <= 0:
            cover = faded(cover, 0.)
    safe_paste(layer, cover, x-pad-(cover.width-size[0])/2, y-pad-(cover.height-size[1])/2)


# 7. Starburst badge ----------------------------------------------------------------------------------------------
def star(cx, cy, rx, ry, depth, spikes, turn, jitter, kind='spiky'):
    points = []
    if kind == 'scallop':  # a puffy comic cloud: round lobes instead of points
        for k in range(spikes*8):
            a = turn+math.tau*k/(spikes*8)
            r = 1-depth*.45*abs(math.sin(a*spikes/2+turn))
            points.append((cx+math.cos(a)*rx*r, cy+math.sin(a)*ry*r))
        return points
    if kind == 'jagged':  # a lopsided blast of a few uneven spikes, the long one pointing up and right
        spikes = 4+int(abs(jitter[0])*1.9)
        turn = -math.pi/6
        ry = max(ry, rx*.62)
    for k in range(spikes*2):
        r = (1 if k % 2 == 0 else 1-depth*(1.2 if kind == 'jagged' else 1))*(1+jitter[k % len(jitter)]*(.2 if kind == 'jagged' else .1)*min(1., depth*4))
        if kind == 'jagged' and k % 2 == 0:
            r *= 1.22 if k == 0 else .9  # one long spike, the rest short
        a = turn+math.pi*k/spikes+(jitter[(k+3) % len(jitter)]*.25 if kind == 'jagged' else 0)
        points.append((cx+math.cos(a)*rx*r, cy+math.sin(a)*ry*r))
    return points


@style('starburst')
def starburst(layer, sprite, x, y, p, effect, pieces, rng, intensity, seed=0):
    """A comic burst in the word's complementary colour (its points, depth and angle different for every word)
    slams open behind it over a hard offset shadow; once it is open, letters punch in one by one, squash on
    landing, and the burst flares and is gone before the word is read."""
    ink = ink_color(sprite)
    burst = contrast_accent(ink, rng)
    rim = contrast_accent(burst, rng)
    left, top, right, bottom = bounds(pieces)
    cx, cy = x+(left+right)/2, y+(top+bottom)/2
    rx = (right-left)/2*1.12+(bottom-top)*.3
    ry = (bottom-top)/2*1.55+(bottom-top)*.15
    size = keyframes(p, [(0, 0.), (.2, 1.12), (.3, .97), (.38, 1.), (.46, 1.), (.7, 1.25)])
    size *= 1+.14*pulse(window(p, .36, .56))  # one breath while it holds
    jitter = [rng.uniform(-1, 1) for _ in range(7)]
    spikes = rng.choice((8, 10, 12, 14)) if rx < ry*2.4 else rng.choice((12, 14, 16))
    spin = rng.uniform(-.6, .6)
    depth = rng.uniform(.24, .36)
    kind = ('spiky', 'scallop')[seed % 2]
    hole = smooth(window(p, .42, .7))  # on the way out a hole opens in the burst until only its rim flies off
    if size > .01 and hole < .995:
        target = layer
        layer = Image.new('RGBA', target.size)
        draw = ImageDraw.Draw(layer)
        turn = spin-.35*(1-min(1., p/.2))+.1*pulse(window(p, .36, .56))  # it turns as it opens and breathes
        off = (bottom-top)*.08*size
        depth = depth*back_out(smooth(window(p, .16, .44)), 1.4)
        draw.polygon(star(cx+off, cy+off, rx*size, ry*size, depth, spikes, turn, jitter, kind), fill=(*darker(burst, .7), 255))
        draw.polygon(star(cx, cy, rx*size*1.04, ry*size*1.04, depth, spikes, turn, jitter, kind), fill=(*rim, 255))
        draw.polygon(star(cx, cy, rx*size*.94, ry*size*.94, depth, spikes, turn, jitter, kind), fill=(*burst, 255))
        ring = window(p, .3, .52)
        if 0 < ring < 1:  # a second ring pulses out from the burst while it holds
            grow = size*(1.04+.11*smoother(ring))
            pts = star(cx, cy, rx*grow, ry*grow, depth, spikes, turn, jitter, kind)
            draw.line(pts+pts[:1], fill=(*rim, 255), width=3, joint='curve')
        if hole > .005:  # punch the hole out of the solid burst (the fill stays opaque)
            draw.polygon(star(cx, cy, rx*size*1.1*hole, ry*size*1.1*hole, depth, spikes, turn, jitter, kind), fill=(0, 0, 0, 0))
        target.alpha_composite(layer)
        layer = target
    snap = window(p, .6, .8)
    if 0 < snap < 1:  # the rim snaps in to an underline flash on the baseline
        span = (right-left)*(1.15-.15*smoother(snap))*(1-smoother(window(snap, .6, 1.)))
        if span > 2:
            line_y = y+bottom+(bottom-top)*.08
            ImageDraw.Draw(layer).rectangle((cx-span/2, line_y, cx+span/2, line_y+max(3, (bottom-top)*.07)), fill=(*rim, 255))
    for index, glyph in enumerate(pieces):
        q = clamp((p-.12)/.34)
        if q <= 0:
            continue
        scale = keyframes(q, [(0, .5), (.38, 1.24), (.56, .92), (.76, 1.03), (1, 1.)])
        squash = 1+.4*pulse(window(q, .4, .7))
        tilt = 0.
        draw_glyph(layer, glyph, x, y, scale*squash**.5, scale/squash**.5, angle=tilt, anchor='middle',
                   image=crisp(glyph.image, clamp((p-.6)/.4)))


# 8. Flip tiles ---------------------------------------------------------------------------------------------------
@style('dot-stamp')
def dot_stamp(layer, sprite, x, y, p, effect, pieces, rng, intensity, seed=0):
    """Each letter arrives printed on its own bright tile, which pops up past full size and then flips over
    like a split-flap card, showing its thick edge as it turns; the back of the tile is the plain letter,
    which drops into place, so the word is spelled out tile by tile."""
    tile = FILL_CYCLE[seed % len(FILL_CYCLE)]
    edge = darker(tile, .4)
    lit = tuple(min(255, round(c+(255-c)*.3)) for c in tile)  # the second shade, clearly lighter
    count = len(pieces)
    left, top, right, bottom = bounds(pieces)
    height = bottom-top
    thickness = max(5., height*.18)
    tile_w = sum(g.width for g in pieces)/len(pieces)*.49  # one tile size for the whole word
    draw = ImageDraw.Draw(layer)
    for index, glyph in enumerate(pieces):
        q = staggered(p, index, count, effect.stagger)
        if q <= 0:
            continue
        pop = keyframes(q, [(0, .95), (.16, 1.16), (.28, .97), (.36, 1.)])
        flip = keyframes(window(q, .3, .66), [(0, 0.), (.32, .24), (.5, .27), (.58, .74), (1., 1.)], ease=smooth)
        turn = math.cos(math.pi*flip)  # 1 front, 0 edge-on, -1 back
        width = abs(turn)
        gx, gy = x+glyph.center, y+(top+bottom)/2
        half_h = height*.6*pop
        if .02 < flip < .98 and width < .6:  # tipping forward: the tile as a trapezoid, its top edge nearer
            tall_h = half_h*max(.3, width)
            near = tile_w*pop*(1+.14*(1-width))
            far = tile_w*pop*(1-.14*(1-width))
            sign = 1 if turn > 0 else -1
            top_w, bottom_w = (near, far) if sign > 0 else (far, near)
            pts = [(gx-top_w, gy-tall_h), (gx+top_w, gy-tall_h), (gx+bottom_w, gy+tall_h), (gx-bottom_w, gy+tall_h)]
            draw.polygon([(a+thickness*.3, b+thickness*.4) for a, b in pts], fill=(*edge, 255))
            draw.polygon(pts, fill=(*(tile if index % 2 == 0 else lit), 255))
            draw_glyph(layer, glyph, x, y, pop*.86, pop*max(.62, width)*.86, anchor='middle',
                       image=crisp(glyph.image, 0.))
        if turn > 0 and not (.02 < flip < .98 and width < .6):
            half_w = tile_w*pop
            lift = height*.05*(1-flip)
            radius = max(1., min(half_w, height*.12))
            tall_h = half_h*width
            draw.rounded_rectangle((gx-half_w, gy-tall_h+thickness*.6, gx+half_w+thickness*.4,
                                    gy+tall_h+thickness*.6), radius=min(radius, tall_h), fill=(*edge, 255))
            draw.rounded_rectangle((gx-half_w, gy-tall_h-lift, gx+half_w, gy+tall_h-lift), radius=min(radius, tall_h),
                                   fill=(*(tile if index % 2 == 0 else lit), 255))
            if width > .18:
                draw_glyph(layer, glyph, x, y, pop*.86, pop*width*.86, dy=-lift, anchor='middle',
                           image=colored(solid_only(glyph.image), (250, 250, 250)))
        else:
            land = 0.
            sy = keyframes(q, [(.5, .8), (.74, 1.12), (.86, .96), (1., 1.)])
            if width < .18:
                continue
            draw_glyph(layer, glyph, x, y, 1., sy*width, dy=height*land, anchor='middle', image=crisp(glyph.image, q))


# 9. Art window -----------------------------------------------------------------------------------------------
@style('art-window')
def art_window(layer, sprite, x, y, p, effect, pieces, rng, intensity, cache=None):
    """The word opens as an oversized window cut through to the artwork itself - the AI painting (or its
    animated video frame) behind the lyrics, magnified and drifting inside the letters, rimmed in the word's
    colour on a hard extrusion - then the word's own ink floods up through it from the baseline behind a bright
    meniscus line, and it settles to size."""
    ink = ink_color(sprite)
    shade = shade_color(ink)
    # Warm print inks only, so the artwork inside the letters never reads as ice or glass.
    meniscus = rng.choice(((210, 20, 70), (230, 70, 10), (170, 20, 140)) if luminance(ink) > .5 else ((255, 196, 40), (255, 120, 60), (255, 150, 200)))
    left, top, right, bottom = bounds(pieces)
    height = bottom-top
    body = solid_only(sprite).getchannel('A')
    # The painting under the word, magnified around the word's own position and slowly pulling back.
    lens = keyframes(p, [(0, 1.1), (.22, 1.55), (.3, 1.55), (.56, 1.03), (.7, .98), (.84, 1.01), (1., 1.)])
    pan = (right-left)*.5*smooth(window(p, .12, .9))  # the painting drifts across inside the letters
    lens = lens*(1+.6*smooth(window(p, .12, .7)))  # and pushes in
    art = Image.blend(window_art(cache, layer.size, sprite.size, x+pan, y, 1/lens, rng),
                      duotone(window_art(cache, layer.size, sprite.size, x+pan, y, 1/lens, rng), darker(meniscus, .7), meniscus, tuple(min(255, c+150) for c in meniscus)), .5)
    from PIL import ImageEnhance
    art = ImageEnhance.Contrast(ImageEnhance.Color(art.convert('RGB')).enhance(1.6)).enhance(1.9).convert('RGBA')
    art = Image.blend(art, Image.new('RGBA', art.size, (*darker(meniscus, .55), 255)), .22)
    fill = Image.new('RGBA', sprite.size)
    fill.paste(art, (0, 0))
    count = len(pieces)
    floods = [smoother(window(p, .3+.24*k/max(1, count-1), .5+.24*k/max(1, count-1))) for k in range(count)]
    flood = min(floods)
    # One smooth surface across the word, higher over the letters that flood first, so no letter is cut square.
    centres = [g.left+g.width/2 for g in pieces]
    levels = [bottom-(bottom-top+height*.1)*f for f in floods]
    xs = np.arange(sprite.width)
    level = np.interp(xs, centres, levels) if count > 1 else np.full(sprite.width, levels[0])
    edge = lambda f: max(6., height*.12)*(1-smoother(window(p, .84, .92)))*(f > 0)  # a thick accent edge that holds
    thick = np.interp(xs, centres, [edge(f) for f in floods]) if count > 1 else np.full(sprite.width, edge(floods[0]))
    rows = np.arange(sprite.height)[:, None]
    rise = Image.fromarray(((rows >= level[None, :])*255).astype('uint8'), 'L')
    held = np.maximum(level, top+thick)  # once the flood reaches the top the line stays inside the letter tops
    line = Image.fromarray((((rows >= held[None, :]-thick[None, :]) & (rows < held[None, :]))*255).astype('uint8'), 'L')
    if max(floods) > 0:
        fill.paste(Image.new('RGBA', sprite.size, (*ink, 255)), (0, 0), rise)
        fill.paste(Image.new('RGBA', sprite.size, (*meniscus, 255)), (0, 0), line)
    fill.putalpha(body)
    rim = Image.new('RGBA', sprite.size, (*ink, 0))
    width = max(1, round(height*.035*(1-flood)))
    rim.putalpha(body.filter(ImageFilter.MaxFilter(width*2+1)))
    rim.alpha_composite(fill)
    if flood >= .999:
        rim = crisp(sprite, clamp((p-.84)/.16*.18+.82))
    scale = keyframes(p, [(0, 1.1), (.16, 1.46), (.34, 1.58), (.56, 1.03), (.7, .98), (.84, 1.01), (1., 1.)])
    depth = height*.12*min(1.4, intensity)*(1-smoother(window(p, .6, .9)))
    cx, cy = (left+right)/2, (top+bottom)/2
    big = stretch(rim, scale, scale)
    if depth >= .6:
        from effects.kinetic import extruded
        big, ox, oy = extruded(big, depth, math.radians(45), shade, darker(shade, .5))
    else:
        ox = oy = 0
    if p >= .995:
        safe_paste(layer, sprite, x, y)
        return
    safe_paste(layer, big, x+cx-cx*scale-ox, y+cy-cy*scale-oy)


def duotone(art, dark, accent, light):
    """The artwork reduced to three printed tones (dark, accent, light) by brightness, like a screen print."""
    grey = np.asarray(art.convert('L'), np.float32)
    low, high = np.percentile(grey, (4, 96))
    grey = np.clip((grey-low)/max(1., high-low), 0, 1)  # full contrast, so faces and shapes stay legible
    tones = np.array([dark, accent, light], np.float32)
    t = np.clip(grey*2, 0, 2)
    low = np.floor(np.clip(t, 0, 1.999)).astype(int)
    f = (t-low)[..., None]
    rgb = tones[low]*(1-f)+tones[np.minimum(low+1, 2)]*f
    out = np.dstack([rgb, np.full(grey.shape, 255, np.float32)]).astype('uint8')
    return Image.fromarray(out, 'RGBA')


def window_art(cache, screen_size, size, x, y, zoom, rng):
    """`size` worth of the artwork behind (x, y), magnified `zoom` times about its centre. The renderer leaves
    the frame's painting in the effect cache as 'backdrop'; without one (previews, tests) a vivid stand-in."""
    backdrop = cache.get('backdrop') if isinstance(cache, dict) else None
    w, h = size
    if backdrop is None:
        hue = rng.random()
        yy, xx = np.mgrid[0:h, 0:w]/np.array((max(1, h), max(1, w)))[:, None, None]
        r = 128+127*np.sin(6.28*(xx*1.3+hue))
        g = 128+127*np.sin(6.28*(yy*1.1+xx*.4+hue+.33))
        b = 128+127*np.sin(6.28*(yy*.7-xx*.6+hue+.66))
        return Image.fromarray(np.stack([r, g, b, np.full_like(r, 255)], -1).astype('uint8'), 'RGBA')
    cx, cy = x+w/2, y+h/2
    half_w, half_h = w/2/zoom, h/2/zoom
    box = (round(cx-half_w), round(cy-half_h), round(cx+half_w), round(cy+half_h))
    return backdrop.crop(box).convert('RGBA').resize((max(1, w), max(1, h)), Image.Resampling.BICUBIC)


# 10. Inflate -----------------------------------------------------------------------------------------------------
def puffed(image, glow, amount):
    """`image`'s letters with a soft balloon highlight (upper left) and a deeper lower edge, by `amount`."""
    if amount <= .01:
        return image
    body = solid_only(image).getchannel('A')
    band = max(2, round(image.height*.07))
    low = ImageChops.subtract(body, ImageChops.offset(body, 0, -band)).point(lambda v: 255 if v > 127 and amount > .5 else 0)
    shadow = Image.new('RGBA', image.size, (*glow, 0))
    shadow.putalpha(low)  # a hard-edged darker lower band: two flat tones, like a print
    out = image.copy()
    out.alpha_composite(shadow)
    return out


@style('inflate')
def inflate(layer, sprite, x, y, p, effect, pieces, rng, intensity):
    """Letters puff up one after another like balloons - glossy, rounded with a highlight - overshoot, wobble
    like jelly as they settle, and lose their shine as they lock flat."""
    ink = ink_color(sprite)
    body_tone = rng.choice(((255, 90, 78), (47, 224, 176), (70, 110, 255), (255, 60, 150)))  # one clean balloon colour
    count = len(pieces)
    for index, glyph in enumerate(pieces):
        q = staggered(p, index, count, effect.stagger)
        if q <= 0:
            continue
        size = keyframes(q, [(0, .9), (.3, 1.18), (.42, 1.18), (1., 1.)], ease=smooth)
        wobble = math.sin(q*math.pi*5)*(1-smoother(window(q, .3, .92)))*.2*min(1.4, intensity)
        sx, sy = size*(1+wobble), size*(1-wobble)
        shine = 1-smoother(window(q, .55, .9))
        plain = crisp(glyph.image, q)
        balloon = colored(solid_only(plain), body_tone) if shine > .5 else plain
        image = puffed(balloon, darker(body_tone, .45), shine)
        swell = pulse(window(q, .15, .75))
        if swell > .05:  # the strokes swell like an inflated balloon
            grow = max(1, round(glyph.height*.05*swell))
            fat = Image.new('RGBA', image.size, (*ink, 0))
            fat.putalpha(solid_only(image).getchannel('A').filter(ImageFilter.MaxFilter(grow*2+1)))
            fat.alpha_composite(image)
            image = fat
        if shine > .05 or luminance(ink) > .6:  # a dark rim so the balloon holds its shape on any ground
            rim = Image.new('RGBA', image.size, (*darker(body_tone if shine > .05 else ink, .5), 0))
            rim.putalpha(solid_only(image).getchannel('A').filter(ImageFilter.MaxFilter(3)))
            rim.alpha_composite(image)
            image = rim
        if False:  # (the specular dash read as a bubble-font preset)
            spec = Image.new('RGBA', image.size)
            sd = ImageDraw.Draw(spec)
            box = solid_only(image).getchannel('A').getbbox()
            if box:
                w, h = box[2]-box[0], box[3]-box[1]
                sd.rounded_rectangle((box[0]+w*.18, box[1]+h*.1, box[0]+w*.42, box[1]+h*.2), radius=h*.05, fill=(255, 255, 255, round(235*shine)))
                spec.putalpha(ImageChops.multiply(spec.getchannel('A'), solid_only(image).getchannel('A')))
                image = image.copy(); image.alpha_composite(spec)
        draw_glyph(layer, glyph, x, y, sx, sy, image=image)


# 11. Depth press -------------------------------------------------------------------------------------------------
def pressed(image, shade, depth, raised):
    """`image` raised on a hard drop shadow (raised > 0) or pressed into the surface with an inset edge."""
    body = solid_only(image)
    out = Image.new('RGBA', (image.width+abs(round(depth))*2+2, image.height+abs(round(depth))*2+2))
    ox = oy = abs(round(depth))+1
    if raised and depth >= 1:
        for d in range(round(depth), 0, -1):  # a solid, hard extrusion-shadow, not a soft drop shadow
            out.alpha_composite(colored(body, shade), (ox+d, oy+d))
        out.alpha_composite(image, (ox, oy))
    else:
        if depth >= 1:  # the press: the face sinks down-right, a hot band showing along its upper-left edge
            sink = round(depth)
            out.alpha_composite(colored(body, shade), (ox, oy))
            out.alpha_composite(image, (ox+sink, oy+sink))
        else:
            out.alpha_composite(image, (ox, oy))
    return out, ox, oy


@style('depth-press')
def depth_press(layer, sprite, x, y, p, effect, pieces, rng, intensity):
    """Letters land one after another raised high above the page on a long hard shadow, then press down into
    it - the shadow swallowed, an inset edge cut along the letter - and spring back level with the surface."""
    from effects.kinetic.glyphs import safe_paste as paste_at
    ink = ink_color(sprite)
    shade = varied_accent(ink, rng)  # a coloured shadow, deepened
    bright = shade
    shade = darker(shade, .35)
    height = max(g.height for g in pieces)
    count = len(pieces)
    for index, glyph in enumerate(pieces):
        q = staggered(p, index, count, effect.stagger)
        if q <= 0:
            continue
        lift = keyframes(q, [(0, 1.), (.26, 1.), (.32, -.5), (.5, -.5), (.62, 0.), (1., 0.)], ease=smooth)  # lands raised, presses in and holds, then rises flush
        scale = 1+.1*lift
        rebound = q > .5
        depth = abs(lift)*height*((.2 if rebound else .16) if lift > 0 else .11)*min(1.4, intensity)
        face = crisp(glyph.image, max(q, .9) if lift < 0 else q)
        if .5 < q < .72:  # it springs back flush with a flash of the hot accent
            face = colored(solid_only(face), bright)
        image = stretch(face, scale, scale)
        drop = (1-smoother(window(q, 0, .16)))*height*.15
        if q < .2:
            scale *= .92+.08*smoother(q/.2)
            image = stretch(crisp(glyph.image, q), scale, scale)
        if lift < 0:  # the press: a deep inset along the upper-left edge
            depth = max(3., height*.06)
        piece, ox, oy = pressed(image, bright if rebound else shade if lift > 0 else bright, depth, lift > 0)
        cx, cy = x+glyph.left+glyph.width/2, y+glyph.image.height/2-drop  # the column's own centre
        paste_at(layer, piece, cx-ox-image.width/2, cy-oy-image.height/2-(depth*.4 if lift > 0 else 0))


# 12. Echo trail --------------------------------------------------------------------------------------------------
@style('echo-trail')
def echo_trail(layer, sprite, x, y, p, effect, pieces, rng, intensity, seed=0):
    """The word skids in from the side trailing solid colour copies of itself, each a step behind and a shade
    deeper; it brakes with a lean, and the copies catch up and stack into it one by one."""
    from effects.kinetic.glyphs import safe_paste as paste_at
    ink = ink_color(sprite)
    left, top, right, bottom = bounds(pieces)
    height = bottom-top
    side = -1 if seed % 2 else 1
    travel = keyframes(p, [(0, 0.), (.4, 1.06), (.52, .98), (.64, 1.), (1., 1.)], ease=smooth)
    reach = min((right-left)*.4, sprite.height*.6)
    lead = side*(1-travel)*reach
    base = far_fills(ink, 1)[0]
    colors = [tuple(min(255, round(c+(255-c)*.25)) for c in base), darker(base, .3), darker(base, .62)]  # light, mid, dark
    keyline = darker(base, .85)
    if p < .12:  # draw on a layer of its own so it can ride in without touching other words
        target, layer = layer, Image.new('RGBA', layer.size)
    letter = (right-left)/max(1, len(pieces))
    count = len(pieces)
    for k in range(3, 0, -1):
        for index, glyph in enumerate(pieces):
            order = index if side > 0 else count-1-index  # the letter nearest the skid's end catches up first
            lag = .16*order/max(1, count-1)
            catch = smoother(window(p, .24+lag+.05*(3-k), .46+lag+.05*(3-k)))
            trail = min(k*letter*.4, k*height*.24)*(1-catch)  # separated echoes behind the skid
            fall = k*height*.07*(1-catch)
            depth = k*max(1., height*.035)*catch*(1-smoother(window(p, .66, .84)))  # then a stepped depth
            if trail < .8 and depth < .5:
                continue
            paste_at(layer, outlined(glyph.image, colors[k-1], keyline, 1), x+glyph.left+lead+side*trail+depth, y+depth+fall)
    lean = side*.22*pulse(window(p, .3, .62))
    word = crisp(sprite, clamp((p-.7)/.3*.18+.82))
    if abs(lean) > .002:
        word = word.transform(word.size, Image.Transform.AFFINE, (1, lean, -lean*bottom, 0, 1, 0), Image.Resampling.BICUBIC)
    tilt = -side*6*(1-smoother(window(p, .12, .52)))  # the word turns level as its echoes catch up
    if abs(tilt) > .05:
        word = word.rotate(tilt, Image.Resampling.BICUBIC, center=(word.width/2, bottom))
    paste_at(layer, word, x+lead, y)
    if p < .12:  # the word and its echoes grow in, opaque, over the first frames
        grow = .55+.45*smoother(p/.12)
        scaled_about(target, layer, 0, 0, x+lead+(left+right)/2, y+(top+bottom)/2, grow)
