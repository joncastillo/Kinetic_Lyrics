"""The storyline: for every illustration (segment) of the song, the moment of the story it shows, who is in it,
where it happens, the camera's shot, and a series of timed beats of what happens, written before any image is made.

The text model writes the whole story in one go, from the user's story and the lyrics, right after the song is
grouped into segments (each segment's length is known then from the timings), and before the image prompts: every
image paints its segment's moment, and every clip's storyboard is split from its segment's beats. The video
step reads it (each video part takes the beats that fall in its stretch of time), the Studio's storyline panel
edits, imports and exports it, and editing it never needs the images. Saved as story.json next to the image
prompts (illustrations.json), so a new set of prompts starts a new story.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

VERSION = 1
BATCH = 6               # segments per director call, to stay well inside its context
FIELD_WORDS = dict(moment=60, characters=60, environment=60, camera=40)
GAZE_RULES = ('For each character, state their gaze target and head orientation in the characters description: '
              'the person they address, the object they handle, the danger they notice, or their direction of travel. '
              'Include changes of attention in the timed actions. Their eyes follow the scene, not the camera. '
              'Use direct eye contact with the viewer only when the user or story explicitly requires it.')
WHOLE_STORY_MAX = 40   # segments the director writes in one call; longer songs are written in batches
ACTION_WORDS, BEAT_CAMERA_WORDS = 60, 30
BEAT_SECONDS = 5.       # about how long a beat lasts when the director writes them
MIN_BEAT = .5
LONG_BEAT = 7.         # a beat longer than this spans two or more video parts, which would repeat it


def story_path(manifest):
    return Path(manifest).parent/'story.json'


def story_text(story):
    """The story text, read from file when given a file path or kept as text."""
    if not story:
        return ''
    try:
        p = Path(story)
        if p.is_file():
            return p.read_text(encoding='utf-8')
    except (OSError, ValueError):
        pass
    return str(story)


def load(manifest):
    try:
        story = json.loads(story_path(manifest).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(story,dict) or not isinstance(story.get('segments'),list):return None
    from direction.reference_choices import apply
    from direction.reference_edits import apply as apply_edits
    return apply(manifest, apply_edits(manifest, story))


def save(manifest, story):
    path = story_path(manifest)
    from core.files import write_text_atomic
    from direction.reference_choices import apply
    from direction.reference_edits import apply as apply_edits
    write_text_atomic(path, json.dumps(apply(manifest, apply_edits(manifest, dict(story, version=VERSION))), ensure_ascii=False, indent=2))


def words(text, limit):
    parts = str(text or '').split()
    return ' '.join(parts[:limit])+('…' if len(parts) > limit else '')


def segment_times(manifest, data, duration, args):
    """[(song start, non-overlapping section length)] per segment; None when
    the timings are unknown. Needs only the prompts' line grouping, not the images."""
    from direction.artwork_sections import section_starts
    job = json.loads(Path(manifest).read_text(encoding='utf-8'))
    illustrations = [Path(manifest).parent/f'{i:03d}.png' for i in range(len(job.get('prompts', [])))]
    if not illustrations or not data or not duration:
        return None
    starts = section_starts(illustrations, data, duration, args)
    if starts is None:
        return None
    boundaries = [0.]+[min(float(duration), max(0., float(s))) for s in starts[1:]]+[float(duration)]
    if any(b <= a for a,b in zip(boundaries,boundaries[1:])):
        raise ValueError('Artwork section times must increase within the song duration')
    return [(round(start,3),round(end-start,3)) for start,end in zip(boundaries,boundaries[1:])]


def retime_story(story, times):
    """Fit all saved actions into their actual song sections without dropping the later beats."""
    changed=False
    for segment,(start,seconds) in zip(story.get('segments',[]),times):
        previous=float(segment.get('seconds') or seconds)
        if abs(previous-seconds)>.0005 or segment.get('start')!=start:
            ratio=seconds/previous if previous>0 else 1.
            beats=[dict(b,start=float(b.get('start',0))*ratio,end=float(b.get('end',previous))*ratio) for b in segment.get('beats',[])]
            segment.update(normalise(dict(segment,beats=beats),seconds),start=start,seconds=seconds)
            if segment['beats']:segment['beats'][-1]['end']=seconds
            changed=True
    return changed


def segments_for_groups(groups, indices, data, end=None):
    """[{index, lyrics, seconds}] for lyric groups before the images exist: a segment lasts from its first line to
    the next segment's first line (the first from 0 s, the last to `end` or four seconds past its last line)."""
    def start_of(line):
        words_ = line.get('words') or []
        return float(words_[0]['start'] if words_ else line.get('start', 0.))
    starts = [0.]+[start_of(data[group[0]]) for group in (indices or [])[1:]] if indices else None
    last_end = max((float((line.get('words') or [{}])[-1].get('end', line.get('end', 0.)) or 0.) for line in data), default=0.)
    finish = float(end) if end else last_end+4.
    segments = []
    for i, lyrics in enumerate(groups):
        if starts and i < len(starts):
            seconds = (starts[i+1] if i+1 < len(starts) else finish)-starts[i]
        else:
            seconds = BEAT_SECONDS*2
        segments.append(dict(index=i, lyrics=lyrics, seconds=max(2., seconds)))
    return segments


def normalise(segment, seconds):
    """A segment the video step can rely on: the four descriptions present and short enough, and beats in order
    that cover the clip from 0 s to its end without gaps or overlaps."""
    seconds = max(.05, float(seconds or segment.get('seconds') or BEAT_SECONDS))
    result = dict(index=int(segment.get('index', 0)), seconds=round(seconds, 3),
                  references=[str(p) for p in segment.get('references') or [] if Path(str(p)).is_file()][:3])
    for key, limit in FIELD_WORDS.items():
        result[key] = words(segment.get(key), limit)
    if 'art_style' in segment:
        result['art_style'] = str(segment.get('art_style') or '').strip()[:4000]
    if segment.get('scene_direction') == 'summary':
        result.update(scene_direction='summary', scene=str(segment.get('scene') or '').strip()[:4000], beats=[])
        return result
    beats = []
    for beat in segment.get('beats') or []:
        if not isinstance(beat, dict):
            continue
        try:
            start, end = float(beat.get('start', 0)), float(beat.get('end', 0))
        except (TypeError, ValueError):
            continue
        action = words(beat.get('action'), ACTION_WORDS)
        if not action or not math.isfinite(start) or not math.isfinite(end):
            continue
        beats.append(dict(start=max(0., start), end=end, camera=words(beat.get('camera'), BEAT_CAMERA_WORDS), action=action))
    beats.sort(key=lambda b: b['start'])
    beats = [b for b in beats if b['start'] < seconds-MIN_BEAT/2] or [dict(start=0., end=seconds, camera='',
             action=result['environment'] and 'The scene breathes with gentle natural motion.' or 'Gentle natural motion.')]
    beats[0]['start'] = 0.
    for k, beat in enumerate(beats):  # each beat runs until the next begins; the last to the clip's end
        beat['end'] = beats[k+1]['start'] if k+1 < len(beats) else seconds
    result['beats'] = [dict(b, start=round(b['start'], 2), end=round(b['end'], 2)) for b in beats if b['end']-b['start'] >= .05]
    if result['beats']:result['beats'][-1]['end']=result['seconds']
    return result


def fallback(index, seconds, scene, character=''):
    """A plain storyline when no director model is available: the painting's scene, a slow camera, gentle motion."""
    count = max(1, round(seconds/BEAT_SECONDS))
    step = seconds/count
    return normalise(dict(index=index, characters=character or 'As painted.', environment=words(scene, 50),
                          camera='One slow, continuous push-in.',
                          beats=[dict(start=k*step, end=(k+1)*step, camera='', action='Gentle natural motion: wind, water, light and foliage move.')
                                 for k in range(count)]), seconds)


def long_beats(segment):
    """True when a beat of the segment lasts longer than LONG_BEAT: each video part it spans would show the same action."""
    return any(b.get('end', 0)-b.get('start', 0) > LONG_BEAT for b in segment.get('beats') or [] if isinstance(b, dict))


def split_long_beats(model, segments, request=None, direction='', story=''):
    """Segments (normalised, in order) whose beats are too long get them rewritten by the director as a series of
    4 to 8 s beats that keep the same events and add the steps between, so every part of the clip moves the story
    on. Changes `segments` in place; returns how many were rewritten. A reply that is no better is ignored."""
    story = story_text(story)
    thin = [s for s in segments if long_beats(s)]
    if not thin or not model:
        return 0
    if request is None:
        from models.ollama.gpu import gpu_chat
        request = lambda payload: gpu_chat('chat', payload, timeout=900)
    from direction.story_rules import ACTION_RULES, GUARDRAILS
    by_index = {s['index']: k for k, s in enumerate(segments)}

    def near(segment, step):
        k = by_index[segment['index']]+step
        return segments[k].get('moment', '') if 0 <= k < len(segments) else ''

    def longest(segment):
        return max((b['end']-b['start'] for b in segment['beats']), default=0.)

    beat_schema = dict(type='object', required=['start', 'end', 'action'],
                       properties=dict(start=dict(type='number'), end=dict(type='number'), action=dict(type='string')))
    schema = dict(type='object', required=['segments'], properties=dict(segments=dict(type='array', items=dict(
        type='object', required=['index', 'beats'],
        properties=dict(index=dict(type='integer'), beats=dict(type='array', items=beat_schema))))))
    rewritten = 0
    for first in range(0, len(thin), BATCH):
        batch = thin[first:first+BATCH]
        payload = dict(model=model, stream=False, think=False, keep_alive=0, format=schema,
                       options=dict(num_ctx=16384, temperature=.7), messages=[dict(role='system', content=(
            'You write the timed beats of a music video told as a short film. Each segment is one painted '
            'illustration animated as one continuous shot, made in parts of about 4 to 5 s; each part shows only '
            'its own beat, so a beat that lasts too long makes several parts repeat the same action. For every '
            'segment given, rewrite `beats` as a timed series covering 0 s to its `seconds`, each beat 3 to 6 s '
            'long, with `start`, `end` and `action` (one or two present-tense sentences of visible, physical action). '+ACTION_RULES+' '
            'Keep the events of the current beats, in order, and add the steps between and after them so the '
            'moment unfolds: every beat shows something new happening and moves the story on; never repeat an '
            'action, and never fill time with pausing, holding still or staring. Stay within the segment\'s '
            '`moment`: do not reach `next_moment`, which comes after it. Same characters, looks, place and light; '
            'no new characters, cuts or scene changes. Continuity: '+GUARDRAILS
            + (f' The story, from the user: {story.strip()}' if str(story or '').strip() else '')
            + (f' Creative direction from the user: {direction.strip()}' if str(direction or '').strip() else '')
            + ' Return JSON {"segments":[{"index":n,"beats":[{"start":0,"end":5,"action":"..."}, ...]}]}.')),
            dict(role='user', content=json.dumps(dict(segments=[dict(
                index=s['index'], seconds=s['seconds'], moment=s.get('moment', ''), characters=s.get('characters', ''),
                environment=s.get('environment', ''), previous_moment=near(s, -1), next_moment=near(s, 1),
                beats=[dict(start=b['start'], end=b['end'], action=b['action']) for b in s['beats']])
                for s in batch]), ensure_ascii=False))])
        try:
            reply = request(payload)
            content = reply['message']['content'] if isinstance(reply, dict) and 'message' in reply else reply
            result = json.loads(content) if isinstance(content, str) else content
        except Exception as exc:  # noqa: BLE001 (the story as written still works; its parts just repeat)
            print(f'Storyline: the long beats of segments {batch[0]["index"]+1}-{batch[-1]["index"]+1} could not be '
                  f'split ({exc}); they stay as written.', flush=True)
            continue
        wanted = {s['index'] for s in batch}
        for entry in result.get('segments', []) if isinstance(result, dict) else []:
            if not isinstance(entry, dict) or entry.get('index') not in wanted or not entry.get('beats'):
                continue
            k = by_index[entry['index']]
            old = segments[k]
            new = normalise(dict(old, beats=entry['beats']), old['seconds'])
            if len(new['beats']) > len(old['beats']) and longest(new) < longest(old):
                segments[k] = dict(old, beats=new['beats'])
                rewritten += 1
    if rewritten:
        print(f'Storyline: split the long beats of {rewritten} segment(s) so each video part moves the story on.',
              flush=True)
    return rewritten


def ensure_split(manifest, story, model, args=None):
    """A saved story whose beats are too long for its clips is split once (see split_long_beats) and saved; the
    `beats_split` mark keeps it from being asked again, so a story the user edits afterwards stays as they wrote it."""
    if not story or story.get('beats_split') or not model:
        return story
    if any(long_beats(s) for s in story['segments']):
        from core.progress import emit
        emit('story', .5, message='Splitting long storyline beats so each video part moves the story on')
        split_long_beats(model, story['segments'], direction=getattr(args, 'image_instructions', '') or '',
                         story=getattr(args, 'story', '') or '')
    story['beats_split'] = True
    save(manifest, story)
    return story


def so_far(written, keep=12):
    """The segments already written, as the next batch needs them to stay consistent: who is in each, where, and
    how it ends (its last beat). The most recent `keep`, so a long song still fits the director's context."""
    recent = [written[i] for i in sorted(written)][-keep:]
    return [dict(index=e['index'], characters=words(str(e.get('characters', '')), 40),
                 environment=words(str(e.get('environment', '')), 30),
                 ends_with=words(str((e.get('beats') or [{}])[-1].get('action', '')), 30)) for e in recent]

MATURE_STORY_RULE = (
    'When the user requests a mature story for adults, preserve its themes, conflicts and emotional stakes. '
    'Describe concrete, visible actions and their consequences rather than replacing difficult events with a '
    'generic mood. Let the story determine the intensity; prioritize shock value. '
    'Allow nudity when storyline requires. Describe sexual acts or sexualized anatomy in detail. Write facial expressions in detail.'
    'Allow violence when storyline requires. Violence may show danger, pain, blood, injury and aftermath. Write about pain and sadistic expressions in detail.'
    'Describe injury in detail such as mutilation, exposed organs and extreme gore. '
    'Keep injuries, emotional reactions and changes to the environment consistent across later segments. '
)

CAMERA_RULES = ('Camera: keep it calm and frame it with intent: choose the angle that tells the moment (a low angle '
                'looking up for strength or suspense, a high angle for vulnerability or to reveal a scene, eye level '
                'for intimacy, a close-up for a clue or an emotion, a wide shot to set the place). The video itself '
                'is shot from a locked-off camera; the shot\'s one slow move is made afterwards in the edit, at a '
                'constant speed in one direction, never reversing. So write `camera` as the framing and angle, then '
                'the move in exactly one of these phrases: "hold", "push in", "pull back", "pan left", "pan right", '
                '"tilt up" or "tilt down" (for example "wide, eye level, slow push in"). Do not describe camera '
                'moves in the beats.')

# How a scene is written from its segment (scene_brief). The video plays forward from the painting, so a painting of
# the outcome leaves it nothing to do and it repaints the shot.
OPENING_FRAME = (
    'Each painting is the first frame of its shot and the video plays forward from it, so it shows the instant just '
    'before the action, not its result. first_action is how the shot begins and story_moment is where it is heading: '
    'paint the start of first_action, with the outcome still to come. Nothing this segment causes has happened yet: '
    'no new wound, bite, break, fall, change or reaction, even where who or story_moment mention one; marks from '
    'earlier segments stay. For "the wolf bites him", paint the wolf at his arm with its jaws closed and his skin '
    'unmarked; for "the glass shatters", the whole glass at the edge of the table. The lyrics only colour it. '
    'Write each description as three labelled parts, in this order, with exactly these labels. "Scene:" what they '
    'are doing at this instant, in one or two sentences: it comes first, as the painter follows what it reads first. '
    '"Characters:" every person, animal and creature in frame, each written out in full with their looks, clothes, '
    'size and position, never "same as before", and anything they hold or carry with its real size against the body. '
    '"Environment:" the place from where, its time of day, light and mood, seen from the angle in shot, with anything '
    'the action needs in view (a surface to crawl on, a tool to reach for). '+GAZE_RULES)


def scene_brief(segment):
    """What a segment gives the writer of its image prompt (see OPENING_FRAME)."""
    beats = segment.get('beats') or []
    first = beats[0].get('action', '') if beats and isinstance(beats[0], dict) else segment.get('scene', '')
    return dict(story_moment=segment.get('moment', ''), who=segment.get('characters', ''),
                where=segment.get('environment', ''), shot=segment.get('camera', ''), first_action=first)


def act_for(fraction):
    """The act of the story a segment belongs to, from where its middle falls in the film (0..1)."""
    return 'opening' if fraction < .2 else 'development' if fraction < .75 else 'climax' if fraction < .9 else 'ending'


def clock(seconds):
    seconds = max(0, int(round(seconds)))
    return f'{seconds//60}:{seconds%60:02d}'


def write_whole_story(model, segments, request, direction='', character='', story=''):
    """{index: entry} for every segment, written in ONE call so the story is conceived as a whole: a beginning, a
    development and an ending spread over the segments in order. None when the reply cannot be used."""
    from direction.story_rules import ACTION_RULES, GUARDRAILS
    beat_schema = dict(type='object', required=['start', 'end', 'action'],
                       properties=dict(start=dict(type='number'), end=dict(type='number'), action=dict(type='string')))
    segment_schema = dict(type='object', required=['index', 'moment', 'characters', 'environment', 'camera', 'beats'],
                          properties=dict(index=dict(type='integer'), moment=dict(type='string'),
                                          characters=dict(type='string'), environment=dict(type='string'),
                                          camera=dict(type='string'), beats=dict(type='array', items=beat_schema)))
    schema = dict(type='object', required=['title', 'plot', 'segments'],
                  properties=dict(title=dict(type='string'), plot=dict(type='string'),
                                  segments=dict(type='array', items=segment_schema, minItems=len(segments),
                                                maxItems=len(segments))))
    told = story_text(story).strip()
    starts, at = [], 0.
    for segment in segments:  # when each segment plays, so the plot is paced by song time
        starts.append(segment.get('start') if isinstance(segment.get('start'), (int, float)) else at)
        at = starts[-1]+float(segment['seconds'])
    total = at
    payload = dict(model=model, stream=False, think=False, keep_alive=0, format=schema,
                   options=dict(num_ctx=32768, num_predict=16000, temperature=.7),
        messages=[dict(role='system', content=(
        MATURE_STORY_RULE+'You are the writer and director of a music video told as a short film. The video is a series of '
            'segments, each one painted illustration that an image-to-video model animates as one continuous shot. '
            'First think of the whole story, then write it: `title`; `plot` (the whole story in four to six '
            'sentences, with a clear beginning, development and ending); then for EVERY segment, in order: '
            '`moment` (one or two sentences: what happens in the story at this point, so that the moments read in '
            'order tell the whole plot), `characters` (exactly who is on screen as the segment opens, before its '
            'beats happen, each once, with the same names, looks and clothes every time they appear, written out in '
            'full, never "same as before"), `environment` (the place, time of day, weather and light), '
            '`camera` (the shot: its framing and angle, then its one slow move), and `beats`: a timed '
            'series covering the segment from 0 s to its `seconds`, each about 4 to 8 s long, with `start` and '
            '`end` in seconds and `action` (one or two present-tense sentences of visible, physical action that '
            'advances the story). '+ACTION_RULES+' '
            + f'The whole video is one short film of {clock(total)}; each segment says when it plays (`song_time`). '
              'Pace the plot by that time, not by counting segments: the setup in the first quarter of the film, the '
              'development (complications, discoveries, rising tension) through the middle half, the climax and '
              'resolution in the last quarter; never resolve the story early, and never spend time on an aftermath '
              'that repeats itself. A long segment carries more of the story than a short one. Every segment moves '
              'the story on. Each segment has an `act`, from when it plays: write its moment for that act and no '
              'other, whatever kind of story it is (a mystery, a romance, a journey, a comedy...). "opening": who, '
              'where, and what they want or face; nothing is settled yet. "development": the story builds through '
              'steps, obstacles, discoveries, setbacks or growing feeling; whatever the story is driving at is NOT '
              'reached in any development segment. "climax": the turning point, where it is reached, revealed or '
              'decided. "ending": what it leads to, and one brief final image. '
            + CAMERA_RULES+' '+GAZE_RULES+' Continuity: '+GUARDRAILS+' The same characters, places and objects carry through the '
            'whole story; what is set up early pays off later. Each segment also suits the lyrics sung over it, but '
            'the story leads; nobody speaks or quotes the lyrics, and the story never retells them. Physically plausible, no text or lettering on screen.'
            + (f' The story to tell, from the user (follow it closely, including where it starts and how it ends): '
               f'{told}' if told else ' Invent a story that the lyrics and the mood of the song suggest.')
            + (f' Creative direction from the user: {direction.strip()}' if str(direction or '').strip() else '')
            + (f' The cast, from the user\'s reference pictures (the story is about them; describe each with '
               f'exactly these looks and outfit every time they appear): {character.strip()}'
               if str(character or '').strip() else '')
            + ' Return JSON {"title":"...","plot":"...","segments":[{"index":0,"moment":"...","characters":"...",'
              '"environment":"...","camera":"...","beats":[{"start":0,"end":5,"action":"..."}]}]} '
              'with one entry for every segment, indexes in order.')),
            dict(role='user', content=json.dumps(dict(segments=[
                dict(index=s['index'], song_time=f"{clock(at)}-{clock(at+s['seconds'])} of {clock(total)}",
                     act=act_for((at+s['seconds']/2)/max(total, 1.)), lyrics=s['lyrics'], seconds=round(s['seconds'], 1),
                     **(dict(painting=words(s['scene'], 80)) if s.get('scene') else {}))
                for s, at in zip(segments, starts)]), ensure_ascii=False))])
    try:
        reply = request(payload)
        content = reply['message']['content'] if isinstance(reply, dict) and 'message' in reply else reply
        result = json.loads(content) if isinstance(content, str) else content
    except Exception as exc:  # noqa: BLE001 (a failed call falls back to writing in batches)
        print(f'Storyline: the whole story could not be written in one go ({exc}); writing it in parts.', flush=True)
        return None
    wanted = {s['index'] for s in segments}
    written = {e['index']: e for e in (result.get('segments') or []) if isinstance(e, dict)
               and e.get('index') in wanted and e.get('beats')} if isinstance(result, dict) else {}
    for entry in written.values():  # a moment left blank is told by the segment's own last beat
        if not str(entry.get('moment') or '').strip():
            entry['moment'] = str((entry['beats'][-1] or {}).get('action', '')) if isinstance(entry['beats'][-1], dict) else ''
    if len(written) < len(wanted)*.8:
        print(f'Storyline: the one-go story covered {len(written)} of {len(wanted)} segments; writing the rest in '
              'parts.', flush=True)
    if isinstance(result, dict) and result.get('plot'):
        print(f'Storyline: {result.get("title", "")}: {words(result["plot"], 80)}', flush=True)
    return written


def write_scene_summaries(model, segments, request, direction='', character='', story=''):
    """AI-built scene descriptions without a second, hidden pass that adds micro directions."""
    from core.progress import emit
    fields = ('moment', 'characters', 'environment', 'camera', 'scene')
    entry_schema = dict(type='object', required=['index', *fields],
                        properties=dict(index=dict(type='integer'), **{k: dict(type='string') for k in fields}))
    schema = dict(type='object', required=['segments'],
                  properties=dict(segments=dict(type='array', items=entry_schema)))
    written = {}
    size = WHOLE_STORY_MAX if len(segments) <= WHOLE_STORY_MAX else BATCH
    for first in range(0, len(segments), size) if request else []:
        batch = segments[first:first+size]
        payload = dict(model=model, stream=False, think=False, keep_alive=0, format=schema,
                       options=dict(num_ctx=32768, num_predict=16000), messages=[
            dict(role='system', content=(MATURE_STORY_RULE+
                 'Construct the scenes of a music video from the story and lyrics, in order. For each segment '
                 'write moment (its place in the story), characters (each visible character or creature, their '
                 'appearance and relative size), environment (place, time, weather and light), camera (framing, '
                 'angle and one slow move), and scene (one coherent paragraph describing what happens). '
                 'Use Scene summary direction: no timestamps, timed beats, mini-scenes, numbered steps or '
                 'micro directions. Describe the overall event and visible outcome, leaving its pacing natural. '
                 'Establish required props at the opening. Keep physical transitions and character identity '
                 'consistent. Do not invent an art style; it is supplied separately. '+CAMERA_RULES+' '+GAZE_RULES)),
            dict(role='user', content=json.dumps(dict(story=story_text(story), lyrics=[s['lyrics'] for s in segments],
                 direction=direction, main_character=character, story_so_far=list(written.values()),
                 segments=batch), ensure_ascii=False))])
        try:
            reply = request(payload)
            content = reply['message']['content'] if isinstance(reply, dict) and 'message' in reply else reply
            result = json.loads(content) if isinstance(content, str) else content
            wanted = {s['index'] for s in batch}
            for entry in result.get('segments', []) if isinstance(result, dict) else []:
                if isinstance(entry, dict) and entry.get('index') in wanted and str(entry.get('scene') or '').strip():
                    written[entry['index']] = entry
        except Exception as exc:
            print(f'Scene summaries unavailable ({exc}); keeping the supplied scene descriptions.', flush=True)
        emit('story', min(1., (first+len(batch))/max(1, len(segments))), message='Writing scene summaries')
    return [normalise(dict(written.get(s['index']) or dict(index=s['index'], characters=character or 'As painted.',
                          environment=s.get('scene', ''), camera='slow push in', scene=s.get('scene') or s['lyrics']),
                          scene_direction='summary'), s['seconds']) for s in segments]


def write_story(model, segments, request=None, direction='', character='', story='', scene_direction='timed'):
    """Storylines for `segments` ({index, scene, lyrics, seconds}) from the director model: the whole story in one
    call, then batches for any segment it missed (each batch sees what is already written); segments still missing
    get the fallback. Returns a list of normalised segments in order."""
    from direction.story_rules import ACTION_RULES, GUARDRAILS
    story = story_text(story)
    if request is None and model:
        from models.ollama.gpu import gpu_chat
        request = lambda payload: gpu_chat('chat', payload, timeout=900)
    if scene_direction == 'summary':
        return write_scene_summaries(model, segments, request, direction, character, story)
    written = {}
    if request and len(segments) <= WHOLE_STORY_MAX:
        written.update(write_whole_story(model, segments, request, direction, character, story) or {})
    missing = [s for s in segments if s['index'] not in written]
    beat_schema = dict(type='object', required=['start', 'end', 'action'],
                       properties=dict(start=dict(type='number'), end=dict(type='number'), action=dict(type='string')))
    segment_schema = dict(type='object', required=['index', 'characters', 'environment', 'camera', 'beats'],
                          properties=dict(index=dict(type='integer'), characters=dict(type='string'),
                                          environment=dict(type='string'), camera=dict(type='string'),
                                          beats=dict(type='array', items=beat_schema)))
    schema = dict(type='object', required=['segments'], properties=dict(segments=dict(type='array', items=segment_schema)))
    overview = [dict(index=s['index'], lyrics=words(s['lyrics'], 25)) for s in segments]
    for first in range(0, len(missing), BATCH) if request else []:
        batch = missing[first:first+BATCH]
        payload = dict(model=model, stream=False, think=False, keep_alive=0, options=dict(num_ctx=32768 if len(story) > 3000 else 16384), format=schema,
            messages=[dict(role='system', content=(
                MATURE_STORY_RULE+'You write the storyline of a music video made of painted illustrations, one per segment of the '
                'song, each animated by an image-to-video model as one continuous shot that starts on its painting. '
                'For every segment give: `characters` (exactly the people and animals in the painting, each once, '
                'with the features that keep them recognisable, or "no one"); `environment` (the place, time of '
                'day, weather and light); `camera` (the framing and angle, then the shot\'s one slow move, e.g. '
                '"wide, eye level, slow push in"); and `beats`: a timed series covering the segment from 0 s to its '
                '`seconds`, each about 4 to 8 s long, with `start` and `end` in seconds and `action` (one or two '
                'present-tense sentences of visible, physical motion: what the characters do, how wind, water, '
                'fabric, hair, foliage, light and weather move). '+ACTION_RULES+' '+CAMERA_RULES+' Continuity rules: '+GUARDRAILS+' Let the scenery lead; '
                'people and animals in the painting move naturally but stay part of the scene. Make the story '
                'develop across the beats and fit the lyrics being sung, and keep neighbouring segments '
                'consistent. The segments are written in order, a few at a time: `story_so_far` holds the ones '
                'already written. Continue from them as one story: the same characters keep the same names, looks, '
                'clothes and companions; places, time of day and weather change only when the painting shows it; '
                'the action picks up where the last segment left off. Physically plausible, no '
                'text or lettering.'
                +(f' Follow the user\'s creative direction: {direction.strip()}' if direction.strip() else '')
                +(f' The video tells this story; the segments are its moments in order, so the storyline carries it '
                  f'from the first segment to the last: {story.strip()}' if str(story or '').strip() else '')
                +(f' The main character is the person from the user\'s reference image: {character.strip()}. Describe '
                  'them with these features whenever they appear.' if character.strip() else '')
                +' Return JSON {"segments":[{"index":n,"characters":"...","environment":"...","camera":"...",'
                '"beats":[{"start":0,"end":5,"action":"..."}, ...]}]} for every segment asked for.')),
                dict(role='user', content=json.dumps(dict(
                    whole_song=overview,
                    story_so_far=so_far(written),
                    write=[dict(index=s['index'], painting=words(s.get('scene') or '', 120), lyrics=s['lyrics'],
                                seconds=round(s['seconds'], 1)) for s in batch]), ensure_ascii=False))])
        try:
            reply = request(payload)
            content = reply['message']['content'] if isinstance(reply, dict) and 'message' in reply else reply
            result = json.loads(content) if isinstance(content, str) else content
        except Exception as exc:
            print(f'Storyline: the director could not write segments {batch[0]["index"]+1}-{batch[-1]["index"]+1} '
                  f'({exc}); they get a plain storyline.', flush=True)
            continue
        wanted = {s['index'] for s in batch}
        for entry in result.get('segments', []) if isinstance(result, dict) else []:
            if isinstance(entry, dict) and entry.get('index') in wanted and entry.get('beats'):
                written[entry['index']] = entry
    told, story = story, []
    for segment in segments:
        entry = written.get(segment['index'])
        story.append(normalise(dict(entry, index=segment['index']), segment['seconds']) if entry else
                     fallback(segment['index'], segment['seconds'], segment['scene'], character))
    if request:
        split_long_beats(model, story, request, direction, told)
    return story


def ensure_story(manifest, data, duration, args, rewrite=False):
    """The story for these prompts: kept when it exists (it may carry the user's edits) and still matches the
    segments, written by the director otherwise or when `rewrite`. Lengths are refreshed from the timings."""
    manifest = Path(manifest)
    job = json.loads(manifest.read_text(encoding='utf-8'))
    times = segment_times(manifest, data, duration, args)
    count = len(job.get('prompts', []))
    if not count:
        return None
    times = times or [(None, BEAT_SECONDS)]*count
    story = None if rewrite else load(manifest)
    model = director_model(args)
    from direction.artwork_sections import main_character
    if story and len(story['segments']) == count:
        changed = retime_story(story,times)
        if not story.get('beats_split') and model:  # a story written before long beats were split
            story = ensure_split(manifest, story, model, args)
        if 'entities' not in story and model:  # a story written before recurring entities were listed
            story['entities'] = list_entities(model, story['segments'], main_character([manifest.parent/'000.png']), getattr(args, 'story', '') or '')
            changed = True
        if changed:
            save(manifest, story)
        return story
    from direction.story_rules import GUARDRAILS  # noqa: F401 (the story's rules come from the motion director)
    from core.progress import emit
    scenes = job.get('visual_descriptions') or job['prompts']
    groups = job.get('groups') or ['']*count
    segments = [dict(index=i, scene=scenes[i] if i < len(scenes) else job['prompts'][i], lyrics=groups[i] if i < len(groups) else '',
                     seconds=times[i][1]) for i in range(count)]
    emit('story', 0, message=f'Writing the storyline for {count} segment{"s" if count != 1 else ""}')
    character = main_character([manifest.parent/'000.png'])
    written = write_story(model, segments, direction=getattr(args, 'image_instructions', '') or '',
                         story=getattr(args, 'story', '') or '', character=character,
                         scene_direction=getattr(args, 'scene_direction', 'timed'))
    from direction.scene_direction import with_style
    written = [with_style(s, dict(job, reference_prompt=getattr(args, 'style_prompt', job.get('reference_prompt', job.get('style_prompt', ''))))) for s in written]
    for segment, (start, _) in zip(written, times):
        segment['start'] = start
    story = dict(segments=written, entities=list_entities(model, written, character, getattr(args, 'story', '') or ''), beats_split=True)
    save(manifest, story)
    emit('story', 1, message='Storyline ready')
    return story


def director_model(args):
    """The text model that writes the story, or None for rule-based runs."""
    model = getattr(args, 'ai_model', None)
    return None if getattr(args, 'director', 'ollama') == 'rules' or not model else model


def ensure_entities(manifest, args):
    """List the recurring entities of a saved storyline that has none listed yet (a story written with the prompts,
    or before entities existed). Runs without video too: the entity pictures guide the images on their own."""
    story, model = load(manifest), director_model(args)
    if not story or 'entities' in story or not model:
        return story
    from direction.artwork_sections import main_character
    story['entities'] = list_entities(model, story['segments'], main_character([Path(manifest).parent/'000.png']), getattr(args, 'story', '') or '')
    save(manifest, story)
    return story


def list_entities(model, segments, character='', story=''):
    """The storyline's recurring characters, objects and places (see direction.entities); [] without a model."""
    from core.progress import emit
    from direction.entities import find_entities
    if not model:
        return []
    emit('story', .9, message='Listing the characters, objects and places that recur across segments')
    return find_entities(model, segments, character=character, story=story)






def validate_import(story, count):
    """A story read from a file (or sent by the panel) checked against this song: one entry per segment."""
    if not isinstance(story, dict) or not isinstance(story.get('segments'), list):
        raise ValueError('This file is not a storyline export')
    if len(story['segments']) != count:
        raise ValueError(f'This storyline has {len(story["segments"])} segments; this song has {count}')
    for number, segment in enumerate(story['segments'], 1):
        if not isinstance(segment, dict):
            raise ValueError(f'Storyline segment {number} is not an object')
        beats = segment.get('beats') or []
        if not isinstance(beats, list):
            raise ValueError(f'Storyline segment {number} has beats that are not a list')
        for beat in beats:
            # Times become numbers here, so nothing downstream (the video step, the panel) sees text in their place.
            try:
                beat['start'], beat['end'] = float(beat['start']), float(beat['end'])
            except (TypeError, KeyError, ValueError):
                raise ValueError(f'A beat in storyline segment {number} needs numeric start and end times') from None
            if not isinstance(beat.get('action'), str):
                raise ValueError(f'A beat in storyline segment {number} has no action')
    return story
