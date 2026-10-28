"""Bounded regeneration, advisory vision review and partial compositor rebuilds."""
from typography_settings import typography_options
import argparse
import sys
import copy
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace

from kinetic_progress import emit
from review_policy import rejected, DEFAULT_THRESHOLD


def keyframe_times(video):
    probe = json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0',
        '-skip_frame','nokey','-show_frames','-show_entries','frame=best_effort_timestamp_time',
        '-of','json',str(video)],text=True,encoding='utf-8',errors='replace'))
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


def vision_review(image, model, lyrics, prompt, subject="", threshold=DEFAULT_THRESHOLD):
    from PIL import Image
    import io
    from filelock import FileLock
    with FileLock(str(image)+'.write.lock',timeout=30):
        snapshot=Path(image).read_bytes()
    fingerprint=hashlib.sha256(snapshot).hexdigest()
    with Image.open(io.BytesIO(snapshot)) as source:
        source.thumbnail((1536, 1536))
        data = io.BytesIO()
        rgba = source.convert('RGBA')
        canvas = Image.new('RGBA',rgba.size,'#f5f2e9')
        canvas.alpha_composite(rgba)
        canvas.convert('RGB').save(data, format='JPEG', quality=94)
    instruction = (
        'Review this illustration, not the reference image. Report only visible issues. '
        'Inspect each visible hand separately for six or more digits, fused fingers, impossible '
        'joint directions, twisted wrists, disconnected fingers, duplicated limbs and malformed appendages; '
        'anatomical continuity, faces, accidental lettering, cropping and relevance to the lyric meaning. '
        'Check believable object construction and physical relationships, not anatomy alone. '
        'Inspect lamp posts and fixtures: light heads should have plausible mounts and recognizable construction; '
        'flag an unexplained light embedded halfway through a pole or disconnected from its fixture. '
        'Check gravity, contact with surfaces, supports, attachment points, consistent scale and perspective, '
        'and obviously conflicting light or shadow directions. Look for floating parts, melted rigid objects, '
        'impossible joints, misplaced functional parts and incoherent object geometry. '
        'Unless explicitly requested otherwise, street lamps must have their light head at the top of the lamp post. '
        'An unrequested light mounted halfway up a continuing pole is an implausible default streetlamp design; flag it and score below 50. '
        'Side-mounted fixtures are acceptable only when explicitly requested. Intentional fantasy must be supported by the requested scene. '
        'Evaluate the entire arrangement, not each object in isolation. Compare repeated objects at similar depth. '
        'Flag abrupt unexplained differences in height, size, proportions or design that do not follow perspective. '
        'For example, a tall lamp post immediately beside a tiny lamp post, or a lit short post beside a taller bare pole, '
        'is an unusual construction unless the requested scene clearly calls for it. '
        'Check for accidental duplicate supports, extra poles, redundant fixtures, mismatched paired objects, '
        'and objects that could not function or coexist naturally in that arrangement. '
        'Do not excuse these defects merely because one individual lamp head is correctly top-mounted. '
        'Distinguish a legitimately more distant smaller object from an implausibly undersized nearby object. '
        'Where one focal streetlamp is intended, an unexplained additional pole or contradictory fixture is a substantial defect. '
        'Describe the relationship and visible evidence, and score below 50 for a clear central scene-level inconsistency. '
        'Stylized brushwork is acceptable; clearly broken construction is still a defect. '
        'Report visible evidence and exact locations; uncertain physical interpretation is not proof. '
        'Do not flag hands merely because some fingers are hidden. If unclear, say uncertain. '
        'Do not deduct any points for fingers that are hidden, occluded, cropped out or not visible. '
        'A closed fist, overlapping hands or no visible fingers is not an anatomical defect. '
        'When no hands are visible, hand anatomy is not applicable and hand_checks must be empty. '
        'Never infer missing or extra fingers from an unseen area. Penalize only defects supported by visible evidence. '
        'Describe visual evidence and location for every reported defect. Do not invent defects. '
        'If a hand is occluded, foreshortened or too small to count, mark it uncertain rather than normal. '
        'SCORING AND ANATOMY POLICY:\n'
        '- The reference image and generated artwork are stylized illustrations/paintings, NOT real photographs. '
        'Artistic license, painterly anatomy, Mucha-style linework, expressive faces, and stylized proportions are acceptable. '
        '- In cases other than extra digits or abnormal appendages (such as stylized faces, painterly brushwork, minor asymmetry, or artistic anatomy), PENALIZE ONLY SLIGHTLY (deduct at most 5 to 10 points; score should remain high: 75-90+). '
        '- Apply a SEVERE, HIGH PENALTY (score must drop below 35, triggering rejection) ONLY for: '
        '  * Extra digits (6 or more fingers on a hand, extra thumbs, duplicate fingers, polydactyly) '
        '  * Abnormal appendages (extra arms, extra legs, extra hands, duplicated limbs, disconnected floating body parts) '
        '  * Clearly legible unwanted lettering, words, numbers or logos in the generated image. Do not mistake decorative strokes for letters. '
        '- A missing focal subject, unrelated scene or severely cropped important subject is a substantial defect and should score below 50. '
        '- Clearly impossible construction or physical relationships central to the subject are substantial defects and should score below 50. '
        '- 50 means usable with minor flaws; below 50 means a substantial visible defect warrants regeneration. '
        'For an object study, anatomy, faces, hair, clothing and human figures are NOT APPLICABLE. '
        'Never penalize an object for lacking human features. '
        'Do not reject a relevant isolated object simply because its drawing technique is understated. '
        'Uncertainty is not proof of a defect; report evidence without inventing problems. '
        'This is an advisory review, never a guarantee. '
        f'Intended visual subject: {subject or "Infer the subject from the actual image and lyrics; do not assume a portrait."}\n'

        f'Lyrics: {lyrics}\nRequested art style: {prompt}')
    schema = dict(type='object', properties=dict(
        summary=dict(type='string'), score=dict(type='integer',minimum=0,maximum=100), uncertain=dict(type='boolean'),
        issues=dict(type='array',items=dict(type='object',properties=dict(
            issue=dict(type='string'),severity=dict(type='string',enum=['low','medium','high']),
            location=dict(type='string')),required=['issue','severity','location'])),
        hand_checks=dict(type='array',items=dict(type='object',properties=dict(
            hand=dict(type='string'),visible_fingers=dict(type=['integer','null']),
            assessment=dict(type='string'),uncertain=dict(type='boolean')),
            required=['hand','visible_fingers','assessment','uncertain']))),
        required=['summary','score','issues','uncertain','hand_checks'])
    payload = dict(model=model, stream=False, keep_alive="30m", think=False, format=schema,
                   options=dict(temperature=.1,num_ctx=8192,num_predict=2200),
                   messages=[dict(role='user', content=instruction,
                                  images=[base64.b64encode(data.getvalue()).decode()])])
    from ollama_gpu import gpu_chat as local_json
    from model_lifecycle import current_session
    session = current_session()
    if session:
        payload['keep_alive']=-1
        session.before_review(model)
    from vision_response import request_review
    def request(query):
        return session.review_request(local_json, query) if session else local_json('chat', query, timeout=600)
    result = request_review(request, payload, lambda message: print('Warning: '+message, flush=True))
    result['threshold']=threshold
    result['rejected']=rejected(result,threshold)
    result['verdict']='rejected' if result['rejected'] else 'accepted'
    return dict(**result, model=model, review_policy_version=2, advisory=True, image=str(image), image_sha256=fingerprint, reviewed_at=time.time())



def generate_candidate(root, job, index, cache, prompt):
    from kinetic_illustrations import run_job
    candidate_job=copy.deepcopy(job)
    folder=root/'candidates'/f'{index:03d}'/str(time.time_ns())
    folder.mkdir(parents=True)
    for key in ('prompts','layouts','visual_descriptions','reference_modes','groups'):
        if key in candidate_job:candidate_job[key]=[candidate_job[key][index]]
    candidate_job['seed']+=time.time_ns()%1000000
    if prompt.strip():candidate_job['prompts'][0]=prompt.strip()
    manifest=folder/'illustrations.json'
    manifest.write_text(json.dumps(candidate_job,indent=2),encoding='utf-8')
    run_job(manifest,cache)
    return folder/'000.png'


def repair_image(root, manifest, index, model, expected_sha, threshold):
    from studio_batches import repair_batch
    repair_batch(sys.modules[__name__], root, manifest,
                 [dict(index=index,model=model,expected_sha=expected_sha)], threshold=threshold)


def generate_and_review(manifest, cache):
    from model_lifecycle import ModelSession
    from studio_batches import process_batch
    from kinetic_illustrations import run_job
    root=manifest.parent.parent.parent
    config_path=root/'config.json'
    config=json.loads(config_path.read_text(encoding='utf-8')) if config_path.is_file() else {}
    with ModelSession([config.get('vision_model')]):
        run_job(manifest,cache)
        from generation_queue import claim_queue,generate_pending,require_replacement_review
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
            from generation_queue import has_pending
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
    from active_artwork import select_manifest
    manifest=select_manifest(args.folder,config)
    job = json.loads(manifest.read_text(encoding='utf-8'))
    if not 0 <= args.index < len(job['prompts']):
        raise ValueError('Invalid illustration index')
    if args.action in ('regenerate','reprompt','verify','repair'):
        from model_lifecycle import ModelSession
        from studio_batches import process_batch
        items=json.loads(args.batch.read_text(encoding='utf-8')) if args.batch else [dict(
            index=args.index,model=args.model,prompt=args.prompt,expected_sha=args.expected_sha,
            candidate=str(args.candidate) if args.candidate else None)]
        if not isinstance(items,list) or any(not isinstance(item,dict) or type(item.get('index')) is not int or not 0<=item['index']<len(job['prompts']) for item in items):
            raise ValueError('Invalid batch illustration indices')
        with ModelSession([config.get('vision_model'), *(item.get('model') for item in items)]):
            process_batch(sys.modules[__name__],args.folder,manifest,args.action,items)
        return
    if args.action in ('patch','rerender'):
        from kinetic_director import Compositor, render
        data = json.loads((args.folder/'video.timings.json').read_text(encoding='utf-8'))
        plan = json.loads((args.folder/'video.design.json').read_text(encoding='utf-8'))
        if config.get('text_animation')=='ai':
            from animation_director import ensure_word_direction
            plan=ensure_word_direction(data,plan,dict(config,_artwork_manifest=str(manifest)))
            (args.folder/'video.design.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
        video = args.folder/'video.mp4'
        duration = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
            'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(video)],
            text=True, encoding='utf-8', errors='replace'))
        illustrations = [manifest.parent/f'{i:03d}.png' for i in range(len(job['prompts']))]
        from realtime_typography import melody_for
        from rhythm import rhythm_for
        options = SimpleNamespace(width=config['width'], height=config['height'], fps=config['fps'], melody=melody_for(args.folder), rhythm=rhythm_for(args.folder),
            font=None, background=None, lead_in=1., illustrations=illustrations, **typography_options(config),
            artwork_mode=config.get('artwork_mode','cutout'), image_seed=config.get('image_seed',42),
            illustration_lines=config['illustration_lines'], cinematic=config['cinematic'], encoder=config['encoder'], preserve_art_slots=True,
            text_animation=config.get('text_animation','directed'), entrance_pool=config.get('entrance_pool'), exit_pool=config.get('exit_pool'),
            entrance_effect=config.get('entrance_effect'), exit_effect=config.get('exit_effect'),
            type_effect=config.get('type_effect','none'), particle_intensity=config.get('particle_intensity',1.), particle_speed=config.get('particle_speed',1.),
            stage_pictures=config.get('stage_pictures','ai-painted'), ai_model=config.get('ai_model','auto'), image_model=config.get('image_model'),
            image_cache=config.get('image_cache'), style_prompt=config.get('style_prompt',''))
        if args.action == 'rerender':
            updated = args.folder/'rerendered.mp4'
            render(Path(config['audio']), updated, data, plan, duration, options)
            from video_versions import archive_video, promote_render_metadata
            archive_video(video)
            updated.replace(video)
            promote_render_metadata(updated, video)
            emit('complete', 1, message='Video rebuilt with updated letter effects and selected images')
            return
        from kinetic_director import tighten_line_starts
        from realtime_typography import melody_for
        from rhythm import rhythm_for
        c = Compositor(tighten_line_starts(data), plan, options.width, options.height, duration, melody=melody_for(args.folder), rhythm=rhythm_for(args.folder),
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
        from kinetic_director import video_color
        options.color = video_color(video)
        patch = args.folder/'patch.mp4'
        emit('render', 0, message=f'Rebuilding affected section {start:.2f}–{end:.2f}s')
        render(Path(config['audio']), patch, data, plan, duration, options)
        merged = args.folder/'updated.mp4'
        mode=splice_section(video,patch,merged,start,end,duration,options.encoder)
        from video_versions import archive_video, promote_render_metadata
        archive_video(video)
        merged.replace(video)
        promote_render_metadata(patch, video, indices={args.index})
        emit('complete', 1, message=f'Updated section {start:.2f}–{end:.2f}s · {mode}')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit(f'Error: {exc}')
