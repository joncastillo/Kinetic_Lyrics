"""Shared composition contract for image prompts and video placement."""


FULL_FRAME = ('fullscreen', 'verse', 'matte')


def illustration_layout(number, width, height, cinematic=False, artwork_mode="cutout", layout_seed=42):
    if artwork_mode == 'matte':
        import random
        rng = random.Random(f'{layout_seed}:{number}:matte-layout')
        sky = rng.uniform(.48, .62)
        margin_x, margin_y = width*.06, height*.05
        text_box = tuple(round(v) for v in (margin_x, margin_y, width-2*margin_x, height*sky-margin_y-height*.06))
        visual = (f'Full-bleed scenery seen from a low viewpoint. The horizon and the scenery along and below it fill the '
                  f'lower {1-sky:.0%} of the canvas. Everything above the skyline, about the upper {sky:.0%} of the canvas, '
                  'is empty sky painted as one flat, perfectly uniform pure chroma-key green (#00FF00): no clouds, sun, moon, '
                  'stars, birds, gradient, texture or shading anywhere in the green. The skyline is a crisp clean edge '
                  'against the green. No main character or dominant figure silhouette; any people are small and below '
                  'the skyline. No border or typography.')
        scale = 1344/max(width, height)
        return dict(position='top', orientation='landscape' if width >= height else 'portrait',
                    art_box=(0, 0, width, height), text_box=text_box, prompt=visual, visual_prompt=visual,
                    artwork_mode=artwork_mode, sky=round(sky, 3), image_width=max(64, round(width*scale/64)*64),
                    image_height=max(64, round(height*scale/64)*64))
    if artwork_mode in ('fullscreen', 'verse'):
        import random
        rng = random.Random(f'{layout_seed}:{number}:background-layout')
        landscape = width >= height
        side = rng.choice(['left', 'right', 'top', 'bottom']) if landscape else rng.choice(['top', 'bottom'])
        tw, th = (rng.uniform(.40, .52), rng.uniform(.46, .68)) if side in ('left', 'right') else (rng.uniform(.65, .86), rng.uniform(.28, .40))
        x = .06 if side == 'left' else .94-tw if side == 'right' else rng.uniform(.06, .94-tw)
        y = .06 if side == 'top' else .94-th if side == 'bottom' else rng.uniform(.06, .94-th)
        text_box = tuple(round(v*s) for v,s in zip((x,y,tw,th),(width,height,width,height)))
        visual = ('Full-bleed painting covering the entire canvas, with coherent scenery and atmospheric depth. '
                  'No blank panel, border, lettering or typography.')
        if artwork_mode == 'verse':
            visual = ('Full-bleed painted scene covering the entire canvas, with a coherent setting and recognizable subjects. '
                      'No blank panel, border or typography.')
        scale = 1344/max(width,height)
        return dict(position=side, orientation='landscape' if landscape else 'portrait',
                    art_box=(0,0,width,height), text_box=text_box, prompt=visual, visual_prompt=visual,
                    artwork_mode=artwork_mode, image_width=max(64,round(width*scale/64)*64),
                    image_height=max(64,round(height*scale/64)*64))
    landscape = width >= height
    position = ('left', 'right', 'center')[number % 3] if cinematic else ('left', 'right')[number % 2]
    if cinematic and landscape:
        art, text = {
            'left': ((0., .02, .48, .96), (.50, .04, .48, .92)),
            'right': ((.52, .02, .48, .96), (.02, .04, .48, .92)),
            'center': ((.15, .01, .70, .70), (.04, .74, .92, .24)),
        }[position]
    elif cinematic:
        art, text = {
            'left': ((0., .02, .62, .67), (.04, .72, .92, .26)),
            'right': ((.38, .02, .62, .67), (.04, .72, .92, .26)),
            'center': ((.04, .01, .92, .68), (.04, .72, .92, .26)),
        }[position]
    elif landscape:
        art, text = (((.07, .19, .26, .62), (.38, 0., .58, 1.)) if position == 'left'
                     else ((.67, .19, .26, .62), (.04, 0., .58, 1.)))
    else:
        art, text = (((.27, .07, .46, .32), (0., .43, 1., .52)) if position == 'left'
                     else ((.27, .61, .46, .32), (0., .05, 1., .52)))
    pixels = lambda box: tuple(round(v*s) for v, s in zip(box, (width, height, width, height)))
    facing = 'right, toward the lyric space' if position == 'left' else 'left, toward the lyric space' if position == 'right' else 'forward or slightly downward toward the lyrics below'
    text_location = ('right' if position == 'left' else 'left') if landscape and position != 'center' else 'below the illustration'
    generation_size = (896, 1152) if position != 'center' else (1536, 1024) if landscape else (1024, 1344)
    prompt = (
        f'LAYOUT CONTRACT: final video {width}x{height}, {"landscape" if landscape else "portrait"}. '
        f'Place the finished illustration at the {position} of the video; lyrics occupy the {text_location}. '
        f'The art area spans {art[2]:.0%} of frame width and {art[3]:.0%} of frame height. '
        f'Orient the subject {facing}; use gaze, gestures or object diagonals toward the reading area. '
        + ('Use a tall close composition. ' if position != 'center' else 'Use a balanced centered composition. ')
        + 'Render the subject large, occupying about 90% of the illustration canvas; leave a small clean margin '
          'around hair and hands. Keep the complete drawn silhouette inside the canvas. '
          'The illustration is a separate cutout: center the subject with any immediate supporting props, surface or setting '
          'within its own canvas. Clean uniform negative space staging background will be removed to true transparency. '
          'No frames, no borders, no lyric text.'
    )
    direction = 'right' if position == 'left' else 'left' if position == 'right' else 'forward'
    visual_prompt = (
        ('Tall portrait-format illustration. ' if position != 'center' or not landscape
         else 'Wide landscape-format illustration. ')
        + f'The subject is oriented {direction}; direct its gaze, gesture or object diagonal {direction}. '
        'For inanimate objects preserve a natural physical form; do not add a face or body. '
        'Large balanced silhouette centered within this illustration canvas, with minimal empty space '
        'and a small clean margin around all extremities. Show the complete described subject. '
        'The complete described subject with its immediate setting on a clean uniform staging background. '
        'Pure drawing and painting; no letters, numbers, symbols, captions or typography.'
    )
    return dict(position=position, orientation='landscape' if landscape else 'portrait',
                art_box=pixels(art), text_box=pixels(text), prompt=prompt,
                visual_prompt=visual_prompt,
                image_width=generation_size[0], image_height=generation_size[1])
