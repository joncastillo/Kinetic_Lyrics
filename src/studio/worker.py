"""Studio worker: bounded regeneration, reviews, repairs and partial video rebuilds."""
from render.typography_settings import typography_options
import argparse
import sys
import copy
import json
import secrets
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
from core.progress import emit
from core.files import replace_file
from core.media import media_duration
from models.vision.review import vision_review  # noqa: F401 (studio.batches calls it as worker.vision_review)


def keyframe_times(video):
    probe = json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0',
        '-skip_frame','nokey','-show_frames','-show_entries','frame=best_effort_timestamp_time',
        '-of','json',str(video)],text=True,encoding='utf-8',errors='replace'))
    return [float(f['best_effort_timestamp_time']) for f in probe.get('frames',[]) if 'best_effort_timestamp_time' in f]


def copy_boundaries(keys, start, end, duration):
    is_key = lambda t: t < .001 or abs(t-duration)<.05 or any(abs(t-k)<.002 for k in keys)
    return is_key(start) and is_key(end)


def section_span(starts, index, duration):
    """The stretch of the video to rebuild for painting `index`. The first painting is on screen from 0 s, through
    the intro, not from its first lyric; starting there left the old still in the intro."""
    start = 0. if index == 0 else starts[index]
    return start, min(duration, starts[index+1]+.9) if index+1 < len(starts) else duration


def splice_section(video, patch, merged, start, end, duration, encoder):
    """Copy untouched GOPs for studio exports; support older videos via overlay."""
    if copy_boundaries(keyframe_times(video),start,end,duration):
        emit('merge',0,message='Copying unchanged video sections; preserving original audio')
        with tempfile.TemporaryDirectory(prefix='splice-',dir=video.parent) as raw:
            folder=Path(raw);pieces=[]
            for name, begin, span in [('before',0.,start),('after',end,duration-end)]:
                if span <= .001:
                    continue
                part=folder/(name+'.mp4')
                subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-ss',str(begin),
                    '-i',str(video),'-t',str(span),'-map','0:v:0','-an','-c:v','copy',str(part)],check=True)
                if name=='before': pieces.append((part,span))
            pieces.append((patch,end-start))
            if (folder/'after.mp4').exists(): pieces.append((folder/'after.mp4',duration-end))
            listing=folder/'segments.txt'
            listing.write_text(''.join("file '"+p.resolve().as_posix().replace("'","'\\''")+"'\nduration "+str(span)+'\n'
                for p,span in pieces),encoding='utf-8')
            emit('merge',.5,message='Joining updated section without re-encoding unaffected frames')
            subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0',
                '-i',str(listing),'-i',str(video),'-map','0:v:0','-map','1:a:0','-c','copy',
                '-t',str(duration),'-movflags','+faststart',str(merged)],check=True)
        return 'stream_copy'
    print('Warning: Legacy video lacks section keyframes. Only changed frames are recomposited; final video encoding uses a compatibility pass.',flush=True)
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(video),'-i',str(patch),
        '-filter_complex',f'[1:v]setpts=PTS+{start}/TB[p];[0:v][p]overlay=eof_action=pass:enable=between(t\\,{start}\\,{end})[v]',
        '-map','[v]','-map','0:a:0','-c:v',encoder,'-pix_fmt','yuv420p','-c:a','copy',
        '-force_key_frames','expr:gte(t,n_forced*1)','-movflags','+faststart',str(merged)],check=True)
    return 'compatibility'


def project_manifest(root, config):
    """The project's active image job, whose storyline and entity sheets a replacement candidate paints with."""
    try:
        from artwork.active import select_manifest
        return select_manifest(Path(root), dict(config, start_step='review'))
    except (OSError, ValueError):
        return None


def generate_candidate(root, job, index, cache, prompt, image_model=None, steps=None):
    from artwork.generation import run_job
    candidate_job=copy.deepcopy(job)
    folder=root/'candidates'/f'{index:03d}'/str(time.time_ns())
    folder.mkdir(parents=True)
    for key in ('prompts','plate_prompts','layouts','visual_descriptions','reference_modes','groups'):
        if key in candidate_job:candidate_job[key]=[candidate_job[key][index]]
    candidate_job['seed']=secrets.randbelow(2**31)  # its own seed: no two candidates, rounds or runs alike
    from models.image.catalog import model_spec, selected_model
    config_path=root/'config.json'
    config=json.loads(config_path.read_text(encoding='utf-8')) if config_path.is_file() else {}
    model=selected_model(job,dict(config,image_model=image_model) if image_model else config)
    if model!=job['model']:candidate_job.update(model=model,steps=model_spec(model)['steps'])
    # The Inference steps setting, not the step count the saved artwork was first made with.
    wanted=steps or (config.get('steps') if model==config.get('image_model') else None)
    if wanted:candidate_job['steps']=max(1,min(150,int(wanted)))
    if prompt.strip():candidate_job['prompts'][0]=prompt.strip()
    # the project's storyline, recurring-entity sheets and this scene's number, which the one-image copy lacks
    candidate_job['source_manifest']=str(job.get('source_manifest') or project_manifest(root, config) or '')
    candidate_job['source_index']=index
    manifest=folder/'illustrations.json'
    manifest.write_text(json.dumps(candidate_job,indent=2),encoding='utf-8')
    run_job(manifest,cache)
    return folder/'000.png'


def paint_references(root, manifest, ids, cache, model=None):
    """Paint the recurring references `ids` again now, from their descriptions, in a one-off job beside the
    project's (it changes no scene). `model` paints them instead of the project's image model."""
    from artwork.generation import run_job
    job = json.loads(Path(manifest).read_text(encoding='utf-8'))
    config_path = root/'config.json'
    config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.is_file() else {}
    folder = root/'candidates'/'references'/str(time.time_ns())
    folder.mkdir(parents=True)
    sheet_job = dict(job, prompts=[], paint_references=list(ids), source_manifest=str(manifest),
                     reuse_references_only=False,
                     ai_model=config.get('ai_model', 'auto'))
    from models.image.catalog import model_spec, selected_model
    model = model or selected_model(job, config)
    sheet_job.update(model=model, steps=config.get('steps') or model_spec(model)['steps'])
    path = folder/'illustrations.json'
    path.write_text(json.dumps(sheet_job, indent=2), encoding='utf-8')
    run_job(path, cache)


def repair_image(root, manifest, index, model, expected_sha, threshold):
    from studio.batches import repair_batch
    repair_batch(sys.modules[__name__], root, manifest,
                 [dict(index=index,model=model,expected_sha=expected_sha)], threshold=threshold)


def paint_all_references(root, manifest, config, cache):
    """Stage 'references': the reference picture of every recurring character, object or place the scenes show,
    painted before any scene is, so one that fails its check is painted again before the scenes that show it."""
    from direction.entities import current_sheet, segment_entities
    from direction.story import load
    from models.image.catalog import model_spec
    job = json.loads(Path(manifest).read_text(encoding='utf-8'))
    source = Path(job.get('source_manifest') or manifest)
    story = load(source) or {}
    if not story.get('entities') or not model_spec(job['model'])['references']:
        return
    matte = job.get('artwork_mode') == 'matte'   # greenscreen scenery: only objects get a picture (see artwork.generation)
    scene_of = (lambda i: int(job['source_index'])) if job.get('source_index') is not None else (lambda i: i)
    needed = {}
    for index in range(len(job['prompts'])):
        if (Path(manifest).parent/f'{index:03d}.png').is_file():
            continue   # painted already (a resume reuses it): its references are painted again only with a new image
        for entity in segment_entities(story, scene_of(index), painted=False, pictured=True):
            if not matte or entity.get('kind') == 'object':   # the cast too: a changed form of the lead is painted from its sheet
                needed.setdefault(entity['id'], entity)
    ids = [i for i, e in needed.items() if not (e.get('image') and Path(str(e['image'])).is_file() and current_sheet(e))]
    if not ids:
        return
    emit('references', 0, message=f'Painting {len(ids)} reference picture(s) before the illustrations')
    paint_references(root, source, ids, cache)




def sheet_text_model(config):
    """The project's text model, which compares a sheet's body parts with its description; None when there is none."""
    from models.ollama.catalog import resolve_prompt_model
    from models.ollama.service import local_json
    try:
        return resolve_prompt_model(local_json, config.get('ai_model', 'auto'))
    except Exception as exc:  # noqa: BLE001 (a check is a help, never a reason to stop the run)
        print(f'Warning: no text model to compare body parts with ({exc}); the sheets get the vision check only.', flush=True)
        return None


def check_references(root, manifest, config, cache, rounds=None, model=None, requeue=True):
    """Stage 'reference-check' (also 'Check reference pictures' on the References tab): the vision model checks each
    new reference picture; one that fails (a stray person, the wrong look, another art style) is painted again and
    checked again, up to `rounds` times (config reference_check_rounds, 10), and the images already painted with a
    picture that failed are queued to be painted again with the new one (not with `requeue` off: sheets painted after
    the images, which never used them). `model` paints them instead of the project's image model."""
    if not config.get('review_references', True) or not config.get('vision_model'):
        return
    from direction.entities import sheet_check_style
    from direction.story import load
    if config.get('start_step')=='images' and config.get('start_substep')=='illustrations':
        return
    from models.vision.sheet_review import review_references
    rounds = max(1, int(config.get('reference_check_rounds') or 10)) if rounds is None else max(1, rounds)
    job = json.loads(Path(manifest).read_text(encoding='utf-8'))
    source = Path(job.get('source_manifest') or manifest)
    style = sheet_check_style(job.get('style_prompt') or '')  # the technique; the mood as the film's, not the sheet's
    text_model = sheet_text_model(config)
    emit('reference-check', 0, message='Checking the reference pictures')
    repainted = set()
    for round_number in range(rounds):
        retry = review_references(source, config['vision_model'], style, prompt=config.get('reference_check_prompt'),
                                  repaint=config.get('repaint_references', True), max_repaints=rounds, text_model=text_model)
        if not retry:
            break
        emit('references', 0, message=f'Painting {len(retry)} reference picture(s) again after the check'
             + (f' (round {round_number+1} of {rounds})' if rounds > 1 else ''))
        paint_references(root, source, retry, cache, model=model)
        repainted |= set(retry)
        emit('reference-check', (round_number+1)/rounds, message='Checking the reference pictures again')
    else:  # every round repainted something: the last picture's verdict is recorded and shown
        review_references(source, config['vision_model'], style, prompt=config.get('reference_check_prompt'), repaint=False,
                          text_model=text_model)
    if not repainted or not requeue:
        return
    story = load(source) or {}
    indices = sorted({i for e in story.get('entities') or [] if e.get('id') in repainted for i in e.get('segments') or []
                      if (source.parent/f'{i:03d}.png').is_file()})
    from artwork.queue import update_queue
    import secrets
    for index in indices:  # painted with the picture that failed: painted again with the new one
        update_queue(root, append=dict(request_id=secrets.token_hex(12), action='regenerate', index=index, prompt='',
                                       model=str(config.get('ai_model') or 'auto'), reason='reference'))
    if indices:
        print('Queued again after their reference was repainted: image(s) '+', '.join(str(i+1) for i in indices)+'.', flush=True)


def generate_and_review(manifest, cache):
    from models.gpu.lifecycle import ModelSession
    from studio.batches import process_batch
    from artwork.generation import run_job
    root=manifest.parent.parent.parent
    config_path=root/'config.json'
    config=json.loads(config_path.read_text(encoding='utf-8')) if config_path.is_file() else {}
    # In order: every reference picture, their check (failed ones painted and checked again), then the illustrations,
    # then their check (rejected ones replaced and checked again by the verify batch's repairs). Checking the
    # references first means no illustration is painted from a picture that fails.
    with ModelSession([config.get('vision_model')]):
        if not (config.get('start_step')=='images' and config.get('start_substep')=='illustrations'):
            paint_all_references(root, manifest, config, cache)
        check_references(root, manifest, config, cache)
        run_job(manifest,cache)
        from artwork.queue import claim_queue, generate_pending, require_replacement_review
        # The queue holds requests for the song's illustrations. A run of the stage's small pictures leaves them for
        # the illustrations' own run: taken here, one was painted with the small pictures' job (cutout, square, no
        # project references).
        illustrations=manifest.parent.parent.name=='video.artwork'
        while True:
            pending=claim_queue(sys.modules[__name__],root) if illustrations else []
            if pending:
                job=json.loads(manifest.read_text(encoding='utf-8'))
                candidates=generate_pending(sys.modules[__name__],root,job,config,pending,manifest=manifest)
                require_replacement_review(root,manifest,candidates)
                if config.get('auto_verify') and config.get('vision_model') and candidates:
                    process_batch(sys.modules[__name__],root,manifest,'verify',[
                        dict(index=c['index'],candidate=c['path'],model=config['vision_model']) for c in candidates])
            if config.get('auto_verify') and config.get('vision_model'):
                emit('illustration-check', 0, message='Checking every illustration')
                job=json.loads(manifest.read_text(encoding='utf-8'))
                items=[dict(index=i,model=config['vision_model'],reuse_review=True) for i in range(len(job['prompts']))]
                process_batch(sys.modules[__name__],root,manifest,'verify',items)
            from artwork.queue import has_pending
            if illustrations and has_pending(root):continue
            emit('auto-review-complete',1,message='Illustration requests and reviews complete; ready for artwork approval')
            break




def write_story(folder, config, manifest):
    """(Re)write the storyline for the current prompts with the director model, from the panel's "Write with AI"."""
    from types import SimpleNamespace
    from direction.story import ensure_story
    from render.timeline import ART_TIMES, load_art_times
    data = json.loads((folder/'video.timings.json').read_text(encoding='utf-8'))
    duration = media_duration(config['audio'])
    args = SimpleNamespace(illustration_lines=config['illustration_lines'], lead_in=1., art_times=load_art_times(folder/ART_TIMES),
                           ai_model=config.get('ai_model'), director=config.get('director', 'ollama'),
                           scene_direction=config.get('scene_direction', 'timed'), style_prompt=config.get('style_prompt', ''),
                           image_instructions=config.get('image_instructions', ''), story=config.get('story_prompt', ''))
    ensure_story(manifest, data, duration, args, rewrite=True)
    emit('complete', 1, message='Storyline written; open the storyline panel to review it')


def illustration_windows(folder, config, manifest, job):
    """(section starts, song duration): when each illustration's clip starts playing in the song (0 for the first)."""
    from types import SimpleNamespace
    from render.timeline import ART_TIMES, load_art_times
    from direction.artwork_sections import section_starts
    data = json.loads((folder/'video.timings.json').read_text(encoding='utf-8'))
    duration = media_duration(config['audio'])
    illustrations = [manifest.parent/f'{i:03d}.png' for i in range(len(job['prompts']))]
    args = SimpleNamespace(illustration_lines=config['illustration_lines'], lead_in=1.,
                           art_times=load_art_times(folder/ART_TIMES))
    starts = section_starts(illustrations, data, duration, args) or [0.]*len(illustrations)
    return [0.]+list(starts[1:]), duration






def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['regenerate', 'reprompt', 'verify', 'repair', 'patch', 'rerender', 'story', 'reference'])
    parser.add_argument('folder', type=Path)
    parser.add_argument('--index', type=int, default=0)
    parser.add_argument('--prompt', default='')
    parser.add_argument('--style', default='')
    parser.add_argument('--model', default='')
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--expected-sha', default='')
    parser.add_argument('--batch', type=Path)
    parser.add_argument('--upscale', default='', help='illustrations whose finished clip is upscaled, e.g. 2,5')
    args = parser.parse_args()
    config = json.loads((args.folder/'config.json').read_text(encoding='utf-8'))
    from artwork.active import select_manifest
    manifest=select_manifest(args.folder,config)
    job = json.loads(manifest.read_text(encoding='utf-8'))
    if not 0 <= args.index < len(job['prompts']):
        raise ValueError('Invalid illustration index')
    if args.action in ('regenerate','reprompt','verify','repair'):
        from models.gpu.lifecycle import ModelSession
        from studio.batches import process_batch
        items=json.loads(args.batch.read_text(encoding='utf-8')) if args.batch else [dict(
            index=args.index,model=args.model,prompt=args.prompt,expected_sha=args.expected_sha,
            candidate=str(args.candidate) if args.candidate else None)]
        if args.action=='verify' and args.prompt.strip() and not args.batch:
            items[0].update(user_prompt=args.prompt.strip(),**({'style':args.style.strip()} if args.style.strip() else {}))
        if not isinstance(items,list) or any(not isinstance(item,dict) or type(item.get('index')) is not int or not 0<=item['index']<len(job['prompts']) for item in items):
            raise ValueError('Invalid batch illustration indices')
        with ModelSession([config.get('vision_model'), *(item.get('model') for item in items)]):
            process_batch(sys.modules[__name__],args.folder,manifest,args.action,items)
        return
    if args.action == 'reference':
        items = json.loads(args.batch.read_text(encoding='utf-8'))
        from core.paths import default_model_cache
        from studio.reference_regeneration import regenerate
        regenerate(sys.modules[__name__], args.folder, manifest, items, config,
                   Path(config.get('image_cache') or default_model_cache()).expanduser().resolve())
        return
    pass
    pass
    if args.action == 'story':
        write_story(args.folder, config, manifest)
        return
    pass
    if args.action in ('patch','rerender'):
        from render.compositor import Compositor, render
        data = json.loads((args.folder/'video.timings.json').read_text(encoding='utf-8'))
        plan = json.loads((args.folder/'video.design.json').read_text(encoding='utf-8'))
        if config.get('text_animation')=='ai' and (config.get('kinetic') or {}).get('overlay_text', True):
            from direction.animation import ensure_word_direction
            plan=ensure_word_direction(data,plan,dict(config,_artwork_manifest=str(manifest)))
            (args.folder/'video.design.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
        video = args.folder/'video.mp4'
        duration = media_duration(video)
        illustrations = [manifest.parent/f'{i:03d}.png' for i in range(len(job['prompts']))]
        from render.realtime import melody_for
        from audio.rhythm import rhythm_for
        from audio.melody import ensure_melody
        from render.timeline import ART_TIMES, load_art_times
        melody = ensure_melody(data, args.folder) or melody_for(args.folder)
        options = SimpleNamespace(width=config['width'], height=config['height'], fps=config['fps'], melody=melody, rhythm=rhythm_for(args.folder),
            art_times=load_art_times(args.folder/ART_TIMES),
            font=None, background=None, lead_in=1., illustrations=illustrations, **typography_options(config),
            artwork_mode=config.get('artwork_mode','cutout'), image_seed=config.get('image_seed',42),
            illustration_lines=config['illustration_lines'], cinematic=config['cinematic'], encoder=config['encoder'], preserve_art_slots=True,
            text_animation=config.get('text_animation','directed'), audio_mode=config.get('audio_mode','original'), entrance_pool=config.get('entrance_pool'), exit_pool=config.get('exit_pool'),
            entrance_effect=config.get('entrance_effect'), exit_effect=config.get('exit_effect'),
            type_effect=config.get('type_effect','none'), particle_intensity=config.get('particle_intensity',1.), particle_speed=config.get('particle_speed',1.),
            stage_pictures=config.get('stage_pictures','ai-painted'), ai_model=config.get('ai_model','auto'), image_model=config.get('image_model'),
            image_steps=config.get('steps'),  # small typography pictures follow the Inference steps setting too
            image_cache=config.get('image_cache'), style_prompt=config.get('style_prompt',''))
        options.video_clips = None
        if args.action == 'rerender':
            updated = args.folder/'rerendered.mp4'
            render(Path(config['audio']), updated, data, plan, duration, options)
            from studio.video_versions import archive_video, promote_render_metadata
            archive_video(video)
            replace_file(updated, video)  # retried while a browser streams the old video
            promote_render_metadata(updated, video)
            emit('complete', 1, message='Video rebuilt with updated letter effects and selected images')
            return
        from render.timeline import tighten_line_starts
        c = Compositor(tighten_line_starts(copy.deepcopy(data)), plan, options.width, options.height, duration, melody=melody, rhythm=options.rhythm, art_times=options.art_times,
            illustrations=illustrations, illustration_lines=options.illustration_lines, cinematic=options.cinematic, preserve_art_slots=True, artwork_mode=options.artwork_mode, layout_seed=options.image_seed,
            type_effect=options.type_effect, entrance_effect=options.entrance_effect, exit_effect=options.exit_effect,
            particle_intensity=options.particle_intensity, particle_speed=options.particle_speed,
            entrance_pool=options.entrance_pool, exit_pool=options.exit_pool, text_animation=options.text_animation,**typography_options(vars(options)))
        start, end = section_span(c.art_starts, args.index, duration)
        import math
        rounded_start, rounded_end = math.floor(start), min(duration, math.ceil(end))
        if copy_boundaries(keyframe_times(video),rounded_start,rounded_end,duration):
            start,end=rounded_start,rounded_end
        else:
            start=math.floor(start*options.fps)/options.fps
            end=min(duration,math.ceil(end*options.fps)/options.fps)
        options.render_start, options.render_end = start, end
        from render.compositor import video_color
        options.color = video_color(video)
        patch = args.folder/'patch.mp4'
        emit('render', 0, message=f'Rebuilding affected section {start:.2f}–{end:.2f}s')
        render(Path(config['audio']), patch, data, plan, duration, options)
        merged = args.folder/'updated.mp4'
        mode=splice_section(video,patch,merged,start,end,duration,options.encoder)
        from studio.video_versions import archive_video, promote_render_metadata
        archive_video(video)
        replace_file(merged, video)
        promote_render_metadata(patch, video, indices={args.index})
        emit('complete', 1, message=f'Updated section {start:.2f}–{end:.2f}s · {mode}')

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit(f'Error: {exc}')
