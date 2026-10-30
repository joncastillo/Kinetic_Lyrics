"""Studio worker: bounded regeneration, reviews, repairs and partial video rebuilds."""
from render.typography_settings import typography_options
import argparse
import sys
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace
from core.progress import emit


def keyframe_times(video):
    probe = json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0',
        '-skip_frame','nokey','-show_frames','-show_entries','frame=best_effort_timestamp_time',
        '-of','json',str(video)],text=True))
    return [float(f['best_effort_timestamp_time']) for f in probe.get('frames',[]) if 'best_effort_timestamp_time' in f]


def copy_boundaries(keys, start, end, duration):
    is_key = lambda t: t < .001 or abs(t-duration)<.05 or any(abs(t-k)<.002 for k in keys)
    return is_key(start) and is_key(end)


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


def generate_candidate(root, job, index, cache, prompt):
    from artwork.generation import run_job
    candidate_job=copy.deepcopy(job)
    folder=root/'candidates'/f'{index:03d}'/str(time.time_ns())
    folder.mkdir(parents=True)
    for key in ('prompts','plate_prompts','layouts','visual_descriptions','reference_modes','groups'):
        if key in candidate_job:candidate_job[key]=[candidate_job[key][index]]
    candidate_job['seed']+=time.time_ns()%1000000
    if prompt.strip():candidate_job['prompts'][0]=prompt.strip()
    manifest=folder/'illustrations.json'
    manifest.write_text(json.dumps(candidate_job,indent=2),encoding='utf-8')
    run_job(manifest,cache)
    return folder/'000.png'


def repair_image(root, manifest, index, model, expected_sha, threshold):
    from studio.batches import repair_batch
    repair_batch(sys.modules[__name__], root, manifest,
                 [dict(index=index,model=model,expected_sha=expected_sha)], threshold=threshold)


def generate_and_review(manifest, cache):
    from models.gpu.lifecycle import ModelSession
    from studio.batches import process_batch
    from artwork.generation import run_job
    root=manifest.parent.parent.parent
    config_path=root/'config.json'
    config=json.loads(config_path.read_text(encoding='utf-8')) if config_path.is_file() else {}
    with ModelSession([config.get('vision_model')]):
        run_job(manifest,cache)
        from artwork.queue import claim_queue, generate_pending, require_replacement_review
        while True:
            pending=claim_queue(sys.modules[__name__],root)
            if pending:
                job=json.loads(manifest.read_text(encoding='utf-8'))
                candidates=generate_pending(sys.modules[__name__],root,job,config,pending)
                require_replacement_review(root,manifest,candidates)
                if config.get('auto_verify') and config.get('vision_model') and candidates:
                    process_batch(sys.modules[__name__],root,manifest,'verify',[
                        dict(index=c['index'],candidate=c['path'],model=config['vision_model']) for c in candidates])
            if config.get('auto_verify') and config.get('vision_model'):
                job=json.loads(manifest.read_text(encoding='utf-8'))
                items=[dict(index=i,model=config['vision_model'],reuse_review=True) for i in range(len(job['prompts']))]
                process_batch(sys.modules[__name__],root,manifest,'verify',items)
            from artwork.queue import has_pending
            if has_pending(root):continue
            emit('auto-review-complete',1,message='Illustration requests and reviews complete; ready for artwork approval')
            break


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['regenerate', 'reprompt', 'verify', 'repair', 'patch', 'rerender'])
    parser.add_argument('folder', type=Path)
    parser.add_argument('--index', type=int, default=0)
    parser.add_argument('--prompt', default='')
    parser.add_argument('--model', default='')
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--expected-sha', default='')
    parser.add_argument('--batch', type=Path)
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
        if not isinstance(items,list) or any(not isinstance(item,dict) or type(item.get('index')) is not int or not 0<=item['index']<len(job['prompts']) for item in items):
            raise ValueError('Invalid batch illustration indices')
        with ModelSession([config.get('vision_model'), *(item.get('model') for item in items)]):
            process_batch(sys.modules[__name__],args.folder,manifest,args.action,items)
        return
    if args.action in ('patch','rerender'):
        from render.compositor import Compositor, render
        data = json.loads((args.folder/'video.timings.json').read_text(encoding='utf-8'))
        plan = json.loads((args.folder/'video.design.json').read_text(encoding='utf-8'))
        if config.get('text_animation')=='ai':
            from direction.animation import ensure_word_direction
            plan=ensure_word_direction(data,plan,dict(config,_artwork_manifest=str(manifest)))
            (args.folder/'video.design.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
        video = args.folder/'video.mp4'
        duration = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
            'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(video)], text=True))
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
            text_animation=config.get('text_animation','directed'), entrance_pool=config.get('entrance_pool'), exit_pool=config.get('exit_pool'),
            entrance_effect=config.get('entrance_effect'), exit_effect=config.get('exit_effect'),
            type_effect=config.get('type_effect','none'), particle_intensity=config.get('particle_intensity',1.), particle_speed=config.get('particle_speed',1.))
        if args.action == 'rerender':
            updated = args.folder/'rerendered.mp4'
            render(Path(config['audio']), updated, data, plan, duration, options)
            from studio.video_versions import archive_video, promote_render_metadata
            archive_video(video)
            updated.replace(video)
            promote_render_metadata(updated, video)
            emit('complete', 1, message='Video rebuilt with updated letter effects and selected images')
            return
        from render.timeline import tighten_line_starts
        c = Compositor(tighten_line_starts(copy.deepcopy(data)), plan, options.width, options.height, duration, melody=melody, rhythm=options.rhythm, art_times=options.art_times,
            illustrations=illustrations, illustration_lines=options.illustration_lines, cinematic=options.cinematic, preserve_art_slots=True, artwork_mode=options.artwork_mode, layout_seed=options.image_seed,
            type_effect=options.type_effect, entrance_effect=options.entrance_effect, exit_effect=options.exit_effect,
            particle_intensity=options.particle_intensity, particle_speed=options.particle_speed,
            entrance_pool=options.entrance_pool, exit_pool=options.exit_pool, text_animation=options.text_animation,**typography_options(vars(options)))
        start = c.art_starts[args.index]
        end = min(duration, c.art_starts[args.index+1]+.9) if args.index+1 < len(c.art_starts) else duration
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
        merged.replace(video)
        promote_render_metadata(patch, video, indices={args.index})
        emit('complete', 1, message=f'Updated section {start:.2f}–{end:.2f}s · {mode}')

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit(f'Error: {exc}')
