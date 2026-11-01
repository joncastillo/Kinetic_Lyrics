"""Local-only lyric studio. No web framework or extra UI dependencies required."""
from render.typography_settings import typography_options
from core.paths import PROJECT_ROOT, SRC_ROOT, UI_ROOT, default_model_cache, studio_output
from core.process import module_command, module_env
import argparse
import copy
import codecs
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import hashlib
import mimetypes
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from urllib.parse import unquote, urlsplit, parse_qs
import webbrowser

from models.image.catalog import MODEL
from direction.illustration_prompts import STYLE_PROMPT
from core.progress import PREFIX
from render.text_effects import EFFECTS, TEXT_ANIMATIONS
from effects.particles.catalog import discover_effects, catalog_choices, validate_choice, parse_pool
from direction.scene_catalog import scene_catalog
from models.image.catalog import MODELS
from video_generation.catalog import MODELS as VIDEO_MODELS, VIDEO_MODES
from models.vision.policy import rejected, DEFAULT_THRESHOLD
from models.speech.catalog import ASR_MODELS, LANGUAGES, DEFAULT_ASR, validate_speech

ROOT = studio_output(PROJECT_ROOT,'lyric-studio')
# Prompting is split into the steps it actually runs; together they take longer than image generation.
STAGES = {'alignment': (0, 8), 'song': (8, 10), 'meanings': (10, 16), 'scenes': (16, 30),
          'fit': (30, 34), 'subjects': (8, 34), 'model': (34, 36),
          'illustrations': (36, 74), 'cutouts': (74, 80), 'review': (80, 80), 'video': (80, 82),
          'direction': (82, 83), 'pictures': (83, 85), 'render': (85, 99), 'complete': (100, 100)}
PROMPT_STAGES = ('subjects', 'song', 'meanings', 'scenes', 'fit')
TOKEN = secrets.token_urlsafe(32)
AUTO_RESUMES = 2
AUTO_RESUME_DELAY = 20
LOCK = threading.RLock()
JOBS = {}
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp'}
AUDIO_SUFFIXES = {'.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.opus', '.webm', '.mp4', '.aiff', '.aif'}


class Job:
    def __init__(self, folder, config):
        self.folder, self.config = folder, config
        self.process = self.action_process = None
        self.cancelled = False
        self.command = None  # the main pipeline command, so a stopped run can be resumed from saved work
        self.runs = 0  # run() calls still in progress, including their post-exit bookkeeping
        self.generation = 0  # bumped on every stop, so a pending automatic resume is dropped
        self.generation_batch = None  # the image requests the running worker owns, retried if it crashes
        self.retry_at = 0
        self.repaired_now = set()  # images a running Verify replaced; their video sections are rebuilt afterwards
        self._image_fingerprints = {}
        self.state = dict(id=folder.name, name=config['name'], status='queued', stage='queued',
            percent=0, message='Waiting to start', started=time.time(), history=[], logs=[], action=None,
            action_percent=0, dirty=[], queued_actions=[])

    def log(self, message, level=None):
        if not message.strip():
            return
        if level is None and (message.startswith('| ') or message.startswith('[LLM ')):
            level = 'error' if message.startswith('[LLM ERROR ') else 'info'
        level = level or ('error' if re.search(r'error|failed|traceback', message, re.I) else
                          'warning' if re.search(r'warn|retry|lettering detected', message, re.I) else 'info')
        with LOCK:
            self.state['logs'].append(dict(time=time.time(), level=level, text=message[:6000]))

    def event(self, event, action=False):
        with LOCK:
            artifact=event.get('manifest') or event.get('artifact')
            if artifact:
                from artwork.active import record_manifest
                candidate=Path(artifact)
                if candidate.name!='illustrations.json':candidate=candidate.parent/'illustrations.json'
                active=record_manifest(candidate) if candidate.resolve().is_relative_to((self.folder/'video.artwork').resolve()) else None
                if active:self.state['active_manifest']=active
            if event['stage']=='queue-claimed':
                requests=event.get('requests',[]);claimed={i.get('request_id') for i in requests}
                self.state['queued_actions']=[i for i in self.state['queued_actions'] if i.get('request_id') not in claimed]
                if self.generation_batch is not None:self.generation_batch['items']+=requests
                self.state['active_images']=sorted(set(self.state.get('active_images',[]))|{i['index'] for i in requests})
                self.state['message']=event.get('message','Queued images added to the batch')
                return
            if event['stage']=='image-start':
                self.state['active_images']=sorted(set(self.state.get('active_images',[]))|{event['index']})
                self.state['action_stage']='illustrations';self.state['message']=event.get('message','Generating replacement')
                return
            if event['stage']=='candidate' and 'index' in event:
                self.state['active_images']=[i for i in self.state.get('active_images',[]) if i!=event['index']]
            if event['stage']=='auto-review-complete':
                self.state['auto_review_queued']=True
                self.state['message']=event.get('message','Batch review complete')
                return
            self.state['message'] = event.get('message', event['stage'])
            fraction = max(0, min(1, float(event.get('fraction') or 0)))
            if action:
                self.state['action_stage']=event['stage']
                if event['stage']=='candidate' and 'index' in event:
                    self.state['active_images']=[i for i in self.state.get('active_images',[]) if i!=event['index']]
                weights = ({'render':(0,85),'merge':(85,100),'complete':(100,100)} if self.state['action'] in ('patch','rerender')
                           else {'model':(0,10),'illustrations':(10,80),'cutouts':(80,100),'candidate':(100,100)}
                           if self.state['action'] in ('regenerate','reprompt') else {})
                lo,hi=weights.get(event['stage'],(0,100))
                self.state['action_percent'] = max(self.state['action_percent'],round(lo+(hi-lo)*fraction,1))
            else:
                stage = event['stage']
                self.state['stage'] = stage
                lo, hi = STAGES.get(stage, (self.state['percent'], self.state['percent']))
                self.state['percent'] = max(self.state['percent'], round(lo+(hi-lo)*fraction, 1))
                if stage == 'review':
                    self.state['status'] = 'review'
                self.state['history'].append([round(time.time()-self.state['started'], 2), self.state['percent']])
            if action and event['stage']=='repair-complete' and event.get('repaired') and (self.folder/'video.mp4').exists():
                index=int(event['index'])
                if index not in self.state['dirty']:self.state['dirty'].append(index)
                self.repaired_now.add(index)
            self.state['detail'] = event
            if not action and event['stage'] == 'review':
                if self.config.get('auto_verify') and self.config.get('vision_model') and not self.state.get('auto_review_queued'):
                    self.queue_reviews(self.config['vision_model'])
                    self.state['auto_review_queued']=True
                self.start_next()

    def queue_reviews(self, model):
        items=self.images()
        for item in items:
            if any(v['current'] for v in item['variants']):
                self.state['queued_actions'].append(dict(action='verify',index=item['index'],model=model))
        self.log(f'Queued anatomy review for {len(items)} illustrations with {model}.')

    def queue_generation(self,index,operation,prompt,model,image_model=None,style=None,steps=None):
        from artwork.queue import update_queue
        item=dict(request_id=secrets.token_hex(12),action=operation,index=index,prompt=prompt,model=model)
        # An art style typed in the regenerate panel applies to this one image; the session style stays as it was.
        if isinstance(style,str) and ' '.join(style.split()):item['style']=' '.join(style.split())
        if image_model is not None:
            if image_model not in {spec['id'] for spec in MODELS}:
                raise ValueError('Choose a supported image model')
            item['image_model']=image_model
        if type(steps) is int and 1 <= steps <= 150:item['steps']=steps
        position=next((i for i,a in enumerate(self.state['queued_actions']) if a.get('action')=='verify'),len(self.state['queued_actions']))
        self.state['queued_actions'].insert(position,item)
        update_queue(self.folder,append=item)

    def start_next(self):
        """Batch prompt work before image work, and image work before reviews."""
        with LOCK:
            if self.cancelled or self.state['action'] or self.state['status'] not in ('review','complete') or not self.state['queued_actions']:
                return
            if time.time() < self.retry_at:return  # a crashed image worker is waiting before its retry
            item=self.state['queued_actions'].pop(0)
            operation=item.get('action','regenerate')
            generation=operation in ('regenerate','reprompt')
            batch=[item];remaining=[]
            for queued in self.state['queued_actions']:
                kind=queued.get('action','regenerate')
                if kind==operation or generation and kind in ('regenerate','reprompt'):batch.append(queued)
                else:remaining.append(queued)
            self.state['queued_actions']=remaining
            if generation:
                from artwork.queue import update_queue
                update_queue(self.folder,remove=[i.get('request_id') for i in batch])
            if generation and any(i.get('action')=='reprompt' for i in batch):operation='reprompt'
            self.generation_batch=dict(items=list(batch),started=time.time()) if generation else None
            self.repaired_now=set()
            command=[*module_command('studio.worker'),operation,str(self.folder),'--index',str(item['index'])]
            if operation in ('verify','repair'):
                command+=['--model',item['model']]
                if operation=='verify' and len(batch)==1 and item.get('user_prompt'):
                    command+=['--prompt',item['user_prompt'],'--style',item.get('style','')]
                if operation=='repair':command+=['--expected-sha',item['expected_sha']]
            elif operation=='regenerate':command+=['--prompt',item.get('prompt','')]
            if generation or len(batch)>1:
                batch_path=self.folder/f'actions-{time.time_ns()}.json'
                batch_path.write_text(json.dumps(batch),encoding='utf-8');command+=['--batch',str(batch_path)]
            if operation=='animate':
                command=[*module_command('studio.worker'),'animate',str(self.folder),'--index',str(item['index'])]
            self.state.update(action=operation,action_percent=0,active_images=[i['index'] for i in batch] if generation else [],
                              action_stage='subjects' if operation=='reprompt' else 'model',message=f'{operation.capitalize()} batch starting')
            threading.Thread(target=self.run,args=(command,operation),daemon=True).start()

    def retry_crashed_generation(self, code):
        """Put a crashed image worker's unfinished requests back in the queue and retry them after a pause.

        A native crash (on Windows usually 0xC0000005 while the image model loads) is most often system RAM running
        out, which a moment later or after other programs release memory may not recur. Called with LOCK held."""
        batch, self.generation_batch = self.generation_batch, None
        if not batch or not native_crash(code):return False
        attempt = max(item.get('crash_retries', 0) for item in batch['items'])+1
        memory = memory_report()
        if attempt > CRASH_RETRIES:
            self.log(f'The image model crashed again (exit {code}) and the regeneration was stopped. {memory} '
                     'This usually means system memory ran out: close memory-heavy programs such as a virtual machine, '
                     'or choose a smaller image model, then regenerate again.', 'error')
            self.state['message'] = 'Image model crashed: not enough free memory?'
            return True
        done = fresh_candidates(self.folder, batch['started'])
        retry = [dict(item, crash_retries=attempt) for item in batch['items'] if item['index'] not in done]
        self.state['queued_actions'] = retry+self.state['queued_actions']
        delay = CRASH_RETRY_DELAY*attempt
        self.retry_at = time.time()+delay
        threading.Timer(delay+.5, self.start_next).start()
        self.log(f'The image model crashed while working (exit {code}), usually because system memory ran out. {memory} '
                 f'Retrying {len(retry)} image request(s) in {delay}s (attempt {attempt}/{CRASH_RETRIES}).', 'warning')
        self.state['message'] = f'Image model crashed; retrying in {delay}s'
        return True

    def rejected_selections(self):
        failures=[]
        for item in self.images():
            for variant in item['variants']:
                review=variant.get('review')
                if not variant['current'] or not review or not rejected(review,self.config.get('review_threshold',DEFAULT_THRESHOLD)):continue
                path=self.folder/variant['path']
                if review.get('image_sha256')==hashlib.sha256(path.read_bytes()).hexdigest():failures.append(item['index'])
        return failures

    def queue_repair(self, command):
        if not self.config.get('auto_repair',True):return
        index=int(command[command.index('--index')+1])
        target=self.manifest().parent/f'{index:03d}.png'
        selected=Path(command[command.index('--candidate')+1]) if '--candidate' in command else target
        if selected.resolve()!=target.resolve():return
        review_path=target.with_suffix('.review.json')
        if not review_path.exists():return
        review=json.loads(review_path.read_text(encoding='utf-8'))
        digest=hashlib.sha256(target.read_bytes()).hexdigest()
        if review.get('image_sha256')!=digest or not rejected(review,self.config.get('review_threshold',DEFAULT_THRESHOLD)):return
        if any(a.get('action')=='repair' and a['index']==index for a in self.state['queued_actions']):return
        model=command[command.index('--model')+1]
        self.state['queued_actions'].append(dict(action='repair',index=index,model=model,expected_sha=digest))
        self.log(f'Illustration {index+1} scored {review["score"]}%; automatic regeneration queued.')

    def run(self, command, action=None):
        with LOCK:
            self.runs += 1
            if not action:self.command = command
        try:self._run(command, action)
        finally:
            with LOCK:self.runs -= 1

    def _run(self, command, action=None):
        try:
            env = module_env(dict(os.environ, PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8', KINETIC_PROGRESS='1',
                                  OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1'))
            kwargs = dict(creationflags=subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == 'nt' else dict(start_new_session=True)
            with LOCK:
                if self.cancelled:
                    return
                process = subprocess.Popen(command, cwd=PROJECT_ROOT.parent, env=env, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, **kwargs)
                if action:
                    self.action_process = process
                else:
                    self.process = process
                    self.state['status'] = 'running'
            self.log(' '.join(str(v) for v in command))
            buffer = ''
            decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
            while True:
                chunk = os.read(process.stdout.fileno(), 4096)
                if not chunk:
                    break
                buffer += decoder.decode(chunk)
                parts = re.split(r'[\r\n]', buffer)
                buffer = parts.pop()
                for line in parts:
                    if line.startswith(PREFIX):
                        try:
                            self.event(json.loads(line[len(PREFIX):]), bool(action))
                        except (ValueError, KeyError, TypeError):
                            self.log(line, 'warning')
                    elif line.strip():
                        self.log(line)
            buffer += decoder.decode(b'', final=True)
            process.stdout.close()
            if buffer.strip():
                self.log(buffer)
            code = process.wait()
            with LOCK:
                if self.cancelled:
                    self.state.update(status='cancelled', message='Cancelled; saved files retained', action=None)
                elif action:
                    if code and action in ('regenerate','reprompt') and self.retry_crashed_generation(code):
                        pass
                    elif code:
                        if action == 'patch':
                            self.state['queued_actions'] = [a for a in self.state['queued_actions'] if a.get('action') != 'patch']
                        self.log(f'{action} failed (exit {code}). See errors above.', 'error')
                    elif action in ('verify', 'repair'):
                        # Verify & rebuild: a repaired image goes straight into the finished video.
                        queued = {a.get('index') for a in self.state['queued_actions'] if a.get('action') == 'patch'}
                        if self.state['status'] == 'complete' and (self.folder/'video.mp4').exists():
                            self.state['queued_actions'].extend(dict(action='patch', index=i)
                                                                for i in sorted(self.repaired_now-queued))
                    elif action == 'rerender':
                        self.state['dirty'] = []
                        self.state['timing_dirty'] = False
                    elif action == 'patch':
                        index = int(command[command.index('--index')+1])
                        self.state['dirty'] = [i for i in self.state['dirty'] if i != index]
                    self.state.update(action=None, active_images=[], action_stage=None, action_percent=100 if not code else 0)
                    if not code and action!='repair':
                        self.state['message'] = f'{action.capitalize()} complete'
                elif code and self.schedule_resume(command, code):
                    self.save()
                    return
                elif code:
                    self.state.update(status='failed', message=f'Generation failed (exit {code})', finished=time.time())
                    self.log(self.state['message'], 'error')
                else:
                    self.state.update(status='complete', percent=100, stage='complete', message='Video ready', finished=time.time())
                if not code and (not action or action in ('patch','rerender')):
                    try:
                        timings=json.loads((self.folder/'video.timings.json').read_text(encoding='utf-8'))
                        at=max(1.2,float(timings[0]['words'][0]['start'])+.35)  # past the fade-in
                        subprocess.run(['ffmpeg','-v','error','-y','-ss',str(at),'-i',str(self.folder/'video.mp4'),
                            '-frames:v','1',str(self.folder/'poster.png')],check=True,capture_output=True)
                    except (OSError,ValueError,KeyError,IndexError,subprocess.CalledProcessError):
                        self.log('Preview poster could not be created; the video is still available.','warning')
                if not code and (not action or action in ('patch','rerender')):
                    from studio.video_versions import verified_changes
                    dirty, verified = verified_changes(self.folder, self.state['dirty'])
                    if verified:self.state['dirty'] = dirty
                if not code and action and action != 'animate':  # never re-queue itself: a clip it could not make would loop
                    self.queue_missing_clips()
                self.save()
                self.start_next()
        except Exception as exc:
            with LOCK:
                self.log(str(exc), 'error')
                self.state.update(action=None, message=str(exc))
                if not action:
                    self.state['status'] = 'failed'
                    self.state['finished'] = time.time()
                self.save()

    def queue_missing_clips(self):
        """Queue the video step for every current illustration without a clip: one that was replaced, regenerated
        or repaired after the video was animated has a new fingerprint and so no clip yet. Only once the video step
        has run for this job; before that the pipeline animates everything itself. Called with LOCK held."""
        model = self.config.get('video_model')
        if (not model or self.config.get('artwork_mode') not in VIDEO_MODES or self.state['status'] not in ('review', 'complete')
                or not (self.folder/'video-clips').is_dir() or self.state.get('action') == 'animate'
                or any(a.get('action') == 'animate' for a in self.state['queued_actions'])):
            return
        try:
            manifest = self.manifest()
            count = len(json.loads(manifest.read_text(encoding='utf-8'))['prompts'])
        except (OSError, ValueError, KeyError):
            return
        from video_generation.clips import clip_folder, image_digest
        missing = [i for i in range(count) if (manifest.parent/f'{i:03d}.png').is_file() and not
                   (clip_folder(self.folder, model, image_digest(manifest.parent/f'{i:03d}.png'))/'clip.json').is_file()]
        if missing:
            self.state['queued_actions'].append(dict(action='animate', index=missing[0], indices=missing))
            self.log('Queued animation for illustration '+', '.join(str(i+1) for i in missing)+'.')

    def resume_command(self, command):
        """The same run, resumed from saved work: the pipeline checkpoint, or else timings, artwork, approval and a plan made by this run."""
        command=[part for part in command if part not in ('--overwrite','--resume')]+['--overwrite','--resume']
        for flag in ('--timings','--plan'):
            if flag in command:
                at=command.index(flag);del command[at:at+2]
        timings=self.folder/'video.timings.json'
        if timings.exists():command+=['--timings',str(timings)]
        design=self.folder/'video.design.json'
        if design.exists() and design.stat().st_mtime>=self.state.get('started',0):command+=['--plan',str(design)]
        if self.state.get('stage') in ('direction','render') and '--review-artwork' in command:
            command.remove('--review-artwork')
        return command

    def schedule_resume(self, command, code):
        attempt=self.state.get('auto_resumes',0)+1
        if self.cancelled or attempt>AUTO_RESUMES:return False
        self.state.update(auto_resumes=attempt,message=f'Recovering automatically after exit {code} (attempt {attempt}/{AUTO_RESUMES})')
        self.log(self.state['message']+f'; resuming from saved work in {AUTO_RESUME_DELAY}s.','warning')
        threading.Thread(target=self.resume_later,args=(self.resume_command(command),self.generation),daemon=True).start()
        return True

    def resume_later(self, command, generation=None):
        time.sleep(AUTO_RESUME_DELAY)
        with LOCK:
            if generation is not None and generation != self.generation:return
            if self.cancelled:
                self.state.update(status='cancelled',message='Cancelled; saved files retained',finished=time.time());self.save()
                return
        self.run(command)

    def save(self):
        (self.folder/'state.json').write_text(json.dumps(self.state), encoding='utf-8')

    def snapshot(self, cursor=0):
        with LOCK:
            result = copy.deepcopy(self.state)
        if (result['status'] == 'cancelled' and result['stage'] == 'complete'
                and (self.folder/'video.mp4').is_file()):
            result['status'] = 'complete'
            result['message'] = 'Video ready; saved work can be edited'
        from studio.video_versions import verified_changes, video_versions
        result['dirty'], result['dirty_verified'] = verified_changes(self.folder, result.get('dirty', []))
        result['video_versions'] = video_versions(self.folder, self.url)
        from artwork.queue import replacement_review_path
        try:
            waiting=json.loads(replacement_review_path(self.folder).read_text(encoding='utf-8'))
            result['replacement_review']=[c['index'] for c in waiting.get('candidates',[])] if waiting.get('manifest')==str(self.manifest()) else []
        except (OSError,ValueError):result['replacement_review']=[]
        logs = result.pop('logs')
        result.update(logs=logs[cursor:], cursor=len(logs), images=self.images(), gallery_cleared=bool(self.gallery_since()), ornaments=self.ornaments(),
                      rejected_images=self.rejected_selections(),
                      elapsed=round(self.state.get('finished', time.time())-self.state['started']),
                      render_settings=dict(**typography_options(self.config),text_animation=self.config.get('text_animation','directed'), audio_mode=self.config.get('audio_mode','original'), auto_accept=self.config.get('auto_accept',False), auto_verify=self.config.get('auto_verify',False), image_instructions=self.config.get('image_instructions',''), cast_reference=self.config.get('reference_use')=='likeness', type_effect=self.config.get('type_effect','none'), entrance_effect=self.config.get('entrance_effect','legacy'), exit_effect=self.config.get('exit_effect','legacy'), entrance_pool=self.config.get('entrance_pool'), exit_pool=self.config.get('exit_pool'), particle_speed=self.config.get('particle_speed',1.), particle_intensity=self.config.get('particle_intensity',1.), image_seed=self.config.get('image_seed'), randomize_seed=self.config.get('randomize_seed', True)))
        prompt_model=self.config.get('ai_model','auto')
        try:
            manifest=json.loads(self.manifest().read_text(encoding='utf-8'))
            prompt_model=manifest.get('prompt_model') or manifest.get('prompt_audit',{}).get('model') or prompt_model
        except (OSError,ValueError,KeyError):pass
        result['production_models']=dict(
            audio=self.config.get('audio_name') or Path(self.config.get('audio','')).name or self.config.get('name',''),
            profile=self.config.get('profile_name',''),
            asr=self.config.get('asr_model',''), alignment=self.config.get('alignment_model','auto'),
            prompt=prompt_model, image=self.config.get('image_model',''),
            vision=self.config.get('vision_model','') if self.config.get('auto_verify') else '',
            encoder=self.config.get('encoder',''), artwork_mode=self.config.get('artwork_mode','cutout'),
            stage_pictures=self.config.get('stage_pictures','ai-painted'))
        if (self.folder/'video.mp4').exists():
            result['video'] = self.url(self.folder/'video.mp4')
        if (self.folder/'poster.png').exists():
            result['poster'] = self.url(self.folder/'poster.png')
        return result

    def url(self, path):
        from urllib.parse import quote
        return '/files/'+self.folder.name+'/'+quote(path.relative_to(self.folder).as_posix())+'?v='+str(path.stat().st_mtime_ns)

    def animation(self, digest):
        """URL of the video step's finished clip for the image with this SHA-256, made with the chosen video model.

        Uploaded clips (`003.mp4`) are a different thing: they replace the slot and come back as `video`."""
        model = self.config.get('video_model')
        if not model:
            return None
        from video_generation.clips import clip_folder
        folder = clip_folder(self.folder, model, digest)
        clip = folder/'clip.mp4'
        return self.url(clip) if (folder/'clip.json').is_file() and clip.is_file() else None

    def manifest(self):
        from artwork.active import select_manifest
        return select_manifest(self.folder,self.config,self.state)

    def ornaments(self):
        """Small painted and library pictures used by the stage, with cached transparent previews."""
        try:
            blocks = json.loads((self.folder/'video.blocks.json').read_text(encoding='utf-8'))['blocks']
        except (OSError, ValueError, KeyError, TypeError):
            return []
        result = []
        for block in blocks:
            ornament = (block or {}).get('ornament') or {}
            image = ornament.get('image')
            kind = ornament.get('library')
            if not image and not kind:
                continue
            try:
                if image:
                    path = Path(image)
                    path = (path if path.is_absolute() else self.folder/path).resolve()
                    if not path.is_file() or not path.is_relative_to(self.folder.resolve()):
                        continue
                    shown = path.with_suffix('.cutout.png')
                    cutout_source = SRC_ROOT/'render'/'glyph_art.py'
                    if not shown.exists() or shown.stat().st_mtime_ns < max(path.stat().st_mtime_ns, cutout_source.stat().st_mtime_ns):
                        from render.glyph_art import cutout
                        cutout(str(path)).save(shown)
                else:
                    from direction.ornaments import library_preview
                    shown = library_preview(kind, self.folder)
                    if shown is None:
                        continue
            except (OSError, ValueError, KeyError):
                continue
            from direction.ornaments import picture_key, released_pictures
            key = picture_key(ornament)
            result.append(dict(word=ornament.get('text', ''), subject=ornament.get('subject') or kind or '',
                               source='painted' if image else 'library', line=ornament.get('line'),
                               url=self.url(shown), key=key, keep=key not in released_pictures(self.folder)))
        return result

    def gallery_since(self):
        """Until a regenerating run reaches review, the gallery shows only images it made; a run that found its
        artwork already made shows it again from review on. 0 when nothing is hidden."""
        regenerating = (self.state.get('status') in ('running', 'queued') and
                        self.state.get('stage') in (None, 'alignment', *PROMPT_STAGES, 'model', 'illustrations', 'cutouts'))
        return self.config.get('gallery_since', 0) if regenerating else 0

    def images(self):
        try:
            manifest = self.manifest()
            job = json.loads(manifest.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            return []
        result = []
        since = self.gallery_since()
        # An older manifest stays hidden until this run paints into it: a run whose prompts are unchanged reuses the
        # same manifest (its folder is a content hash), so its new pictures must still appear as they are made.
        if since and manifest.stat().st_mtime < since and not any(
                p.stat().st_mtime >= since for p in manifest.parent.glob('[0-9][0-9][0-9]*.png')):
            return []
        for i, prompt in enumerate(job['prompts']):
            current, raw = manifest.parent/f'{i:03d}.png', manifest.parent/f'{i:03d}.raw.png'
            variants = [p for p in (current, raw) if p.exists()]
            variants += sorted((self.folder/'candidates'/f'{i:03d}').glob('*/*.png'))
            variants += sorted((self.folder/'versions'/f'{i:03d}').glob('*.png'))
            variants = [p for p in variants if not since or p.stat().st_mtime >= since]
            entries = []
            seen = set()
            for path in variants:
                if '.tmp.' in path.name or '.rejected-' in path.name or path.name.endswith('.plate.png') or (path.name == '000.raw.png' and path.parent != manifest.parent):
                    continue
                stat = path.stat()
                signature = (stat.st_mtime_ns, stat.st_size)
                cached = self._image_fingerprints.get(path)
                if cached is None or cached[:2] != signature:
                    cached = (*signature, hashlib.sha256(path.read_bytes()).hexdigest())
                    self._image_fingerprints[path] = cached
                fingerprint = cached[2]
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                review = None
                if path.with_suffix('.review.json').exists():
                    try:
                        review = json.loads(path.with_suffix('.review.json').read_text(encoding='utf-8'))
                    except (OSError, ValueError):
                        pass
                from artwork.metadata import variant_metadata
                metadata=variant_metadata(path,job,i)
                from artwork.video_art import sidecar
                clip=sidecar(path)
                animation=self.animation(fingerprint) if not clip else None
                entries.append(dict(prompt=metadata.get('prompt',prompt),subject=metadata.get('subject',''),style=metadata.get('style',''),video=self.url(clip) if clip else None,animation=animation,path=path.relative_to(self.folder).as_posix(), url=self.url(path),
                    current=path == current, raw=path == raw, fresh=path.is_relative_to(self.folder/'candidates') and stat.st_mtime>=self.state['started'], review=review))
            queued=next((q for q in self.state.get('queued_actions',[]) if q.get('index')==i and q.get('action','regenerate') in ('regenerate','reprompt')),None)
            pending=('Prompt queued' if queued.get('action')=='reprompt' else 'Image queued') if queued else ''
            if i in self.state.get('active_images',[]) :
                pending='Preparing prompt' if self.state.get('action_stage') in PROMPT_STAGES else 'Generating replacement'
            result.append(dict(index=i, pending=pending, subject=job.get('visual_descriptions', job['prompts'])[i],
                lyrics=job['groups'][i], prompt=prompt, style=job.get('style_prompt',self.config.get('style_prompt','')), variants=entries))
        return result


def checked_file(job, value):
    path = (job.folder/value).resolve()
    if not path.is_relative_to(job.folder.resolve()) or not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError('Select an image belonging to this job')
    return path


def stop_job(job):
    with LOCK:
        if job.state['status'] == 'complete' and not job.state.get('action'):
            return
        job.cancelled = True
        job.generation += 1
        from artwork.queue import queue_path
        queue_path(job.folder).unlink(missing_ok=True)
        for process in (job.action_process, job.process):
            if process and process.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
                else:
                    os.killpg(process.pid, signal.SIGTERM)
        job.state.update(status='cancelled', action=None, queued_actions=[], message='Cancelled; saved files retained', finished=time.time())
        job.save()


CRASH_RETRIES = 2
CRASH_RETRY_DELAY = 20


def native_crash(code):
    """A process killed by the OS or a native fault, not a Python error (exit 1) the same inputs would repeat."""
    return code < 0 or code >= 0xC0000000


def memory_report():
    try:
        import psutil
        ram, swap = psutil.virtual_memory(), psutil.swap_memory()
        return (f'Free memory now: {ram.available/2**30:.1f} of {ram.total/2**30:.1f} GiB RAM, '
                f'{swap.free/2**30:.1f} GiB page file.')
    except Exception:
        return ''


def fresh_candidates(folder, since):
    """Illustration indices that received a finished candidate after `since`."""
    done = set()
    for image in (folder/'candidates').glob('*/*/000.png'):
        try:
            if int(image.parent.name) >= since*1e9:done.add(int(image.parent.parent.name))
        except ValueError:pass
    return done


def video_busy(job):
    alive = job.process is not None and job.process.poll() is None
    return bool(job.state.get('action')) or job.state['status'] in ('running', 'queued') or (job.state['status'] == 'review' and alive)


def stop_video_work(job):
    """Stop the video being made so edited timings can be saved. Returns what restart_video_work starts again."""
    from artwork.queue import queue_path
    with LOCK:
        action = job.state.get('action')
        if action and action not in ('rerender', 'patch'):
            raise ValueError('Wait for the current image operation to finish before saving timings')
        kind = 'rerender' if action else 'run'
        if kind == 'run' and not job.command:
            raise ValueError('This run started before the studio restarted. Cancel it, then save the timings.')
        status, queued = job.state['status'], list(job.state['queued_actions'])
        pending = queue_path(job.folder).read_text(encoding='utf-8') if queue_path(job.folder).exists() else None
    stop_job(job)
    deadline = time.time()+60
    while True:
        with LOCK:
            if not job.runs:break
        if time.time() > deadline:
            raise ValueError('The current video operation did not stop. Try saving again.')
        time.sleep(.2)
    with LOCK:  # queued image requests are not part of the video; keep them
        job.state['queued_actions'] = queued
        if pending is not None:queue_path(job.folder).write_text(pending, encoding='utf-8')
    return kind, status


def restart_video_work(job, kind, status):
    with LOCK:
        job.cancelled = False
        if kind == 'rerender':
            command = [*module_command('studio.worker'), 'rerender', str(job.folder)]
            job.state.update(status='complete' if status == 'cancelled' else status, action='rerender', action_percent=0,
                             message='Rebuilding the video with the edited word timings')
            args = (command, 'rerender')
        else:
            command = job.resume_command(job.command)
            job.state.update(status='running', action=None, auto_resumes=0, timing_dirty=False,
                             message='Restarting video generation with the edited word timings')
            args = (command,)
        job.log('Word timings edited in the timeline; the running video was stopped and restarted with them.', 'warning')
        job.save()
    threading.Thread(target=job.run, args=args, daemon=True).start()


def parse_form(body, content_type):
    message = BytesParser(policy=default).parsebytes(
        b'Content-Type: '+content_type.encode()+b'\r\nMIME-Version: 1.0\r\n\r\n'+body)
    if not message.is_multipart():
        raise ValueError('Expected multipart form data')
    fields, files = {}, {}
    for part in message.iter_parts():
        name = part.get_param('name', header='content-disposition')
        if not name:
            continue
        data = part.get_payload(decode=True) or b''
        if part.get_filename():
            files.setdefault(name, []).append((part.get_filename(), data))
        else:
            fields[name] = data.decode('utf-8')
    return fields, files


def store_image(folder, filename, content):
    from PIL import Image
    import io
    if Path(filename).suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError('Reference and replacement images must be PNG, JPEG or WebP')
    with Image.open(io.BytesIO(content)) as image:
        image.verify()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/(secrets.token_hex(8)+'.png')
    with Image.open(io.BytesIO(content)) as image:
        image.convert('RGBA').save(path)
    return path


def forget_audio_analysis(folder):
    """Remove everything measured from a project's previous audio track."""
    for name in ('video.timings.json', 'video.melody.json', 'video.rhythm.json', 'vocals.wav',
                 'video.graph.sqlite', 'video.graph.sqlite-wal', 'video.graph.sqlite-shm'):
        (folder/name).unlink(missing_ok=True)
    shutil.rmtree(folder/'stems', ignore_errors=True)


def start_job(fields, files):
    with LOCK:
        if any(j.state['status'] in ('queued', 'running', 'review') or j.state['action'] for j in JOBS.values()):
            raise ValueError('Finish or cancel the active job before starting another GPU job')
        project_id = fields.get('project_id', '').strip()
        start_step = fields.get('start_step', 'beginning').strip()
        ai_model = fields.get('ai_model', 'auto').strip()
        is_restart = bool(start_step != 'beginning' and project_id and (ROOT / project_id).is_dir())
        if ai_model not in ('','auto') or fields.get('auto_verify')=='on':
            from models.ollama.catalog import validate_selected_models
            ai_model=validate_selected_models(ai_model,fields.get('vision_model',''),fields.get('auto_verify')=='on')

        if not files.get('audio'):
            if is_restart:
                existing_audio = sorted((ROOT / project_id).glob('audio.*'), key=lambda p: p.stat().st_mtime_ns)
                if existing_audio:
                    filename = existing_audio[-1].name
                    audio_bytes = existing_audio[-1].read_bytes()
                else:
                    raise ValueError('Choose an audio file')
            else:
                raise ValueError('Choose an audio file')
        else:
            filename, audio_bytes = files['audio'][0]
        suffix = Path(filename).suffix.lower()
        if suffix not in AUDIO_SUFFIXES or not audio_bytes:
            raise ValueError('Unsupported or empty audio file')
        from pipeline.timing import sanitize_lyrics
        lyrics = sanitize_lyrics(fields.get('lyrics', '')).strip()
        if is_restart and start_step in ('prompts', 'images', 'review', 'render'):
            try:
                previous_lyrics = sanitize_lyrics((ROOT / project_id / 'lyrics.txt').read_text(encoding='utf-8')).strip()
            except OSError:
                previous_lyrics = None
            if previous_lyrics is not None and lyrics != previous_lyrics:
                start_step = 'timing'
        width, height = {'720p': (1280, 720), '1080p': (1920, 1080), 'portrait': (720, 1280)}[fields.get('resolution', '720p')]
        asr_model=fields.get('asr_model',DEFAULT_ASR)
        alignment_model=fields.get('alignment_model','auto')
        validate_speech(asr_model,fields.get('language','auto'),alignment_model,has_lyrics=bool(lyrics))
        image_model = fields.get('image_model', MODEL)
        spec = next((m for m in MODELS if m['id'] == image_model), None)
        if spec is None:
            raise ValueError('Choose a supported image model')
        steps, lines = int(fields.get('steps') or spec['steps']), str(fields.get('lines', 'auto')).strip().lower()
        if not 1 <= steps <= 150 or (lines != 'auto' and (not lines.isdecimal() or not 1 <= int(lines) <= 50)):
            raise ValueError('Steps must be 1–150; lines per image must be Auto or 1–50')
        if lines != 'auto':
            lines = int(lines)
        if is_restart:
            folder = ROOT / project_id
        else:
            folder = ROOT/(time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3))
            folder.mkdir(parents=True, exist_ok=True)
        audio = folder/('audio'+suffix)
        previous_audio = list(folder.glob('audio.*'))
        audio_replaced = bool(previous_audio) and not any(p.read_bytes() == audio_bytes for p in previous_audio)
        if audio_replaced:
            for path in previous_audio:
                path.unlink()
            forget_audio_analysis(folder)
            if start_step in ('prompts', 'images', 'review', 'render'):
                # Saved timings belong to the old track; artwork for unchanged lyrics is still reused.
                start_step = 'timing'
        if audio_replaced or not audio.exists():
            audio.write_bytes(audio_bytes)
        (folder/'lyrics.txt').write_text(lyrics, encoding='utf-8')
        refs = [store_image(folder/'references', name, content) for name, content in files.get('references', [])]
        seed_val = fields.get('image_seed', fields.get('seed', ''))
        seed_field = str(seed_val).strip() if seed_val is not None else ''
        randomize = fields.get('randomize_seed') in ('on', 'true', '1') or seed_field in ('', '-1', 'random')
        if randomize:
            image_seed = secrets.randbelow(2**31)
        else:
            try:
                image_seed = int(seed_field)
            except ValueError:
                image_seed = secrets.randbelow(2**31)
        if is_restart and start_step in ('images','review','render') and not seed_field:
            try:image_seed=json.loads((folder/'config.json').read_text(encoding='utf-8')).get('image_seed',image_seed)
            except (OSError,ValueError):pass
        if is_restart and not files.get('audio'):
            try:filename=json.loads((folder/'config.json').read_text(encoding='utf-8')).get('audio_name',filename)
            except (OSError,ValueError):pass
        from direction.image_instruction_cleanup import clean_legacy_imported_meaning
        config = dict(name=Path(filename).stem, audio=str(audio), audio_name=filename,
            profile_name=str(fields.get('profile_name','')).strip()[:80], width=width, height=height, fps=30,
            image_cache=str(Path(fields.get('cache', '').strip() or str(default_model_cache())).expanduser().resolve()),
            style_prompt=fields.get('reference_prompt', '').strip() or STYLE_PROMPT,
            image_instructions=clean_legacy_imported_meaning(fields.get('image_instructions', ''))[:2000],
            reference_use='likeness' if fields.get('cast_reference') == 'on' else 'style',
            theme=fields.get('style', '').strip() or 'Bright, uplifting mood; flowing fabric and long flowing hair; graceful movement and luminous color.',
            artwork_mode=fields.get('artwork_mode','cutout'), image_seed=image_seed, randomize_seed=randomize,
            cinematic=fields.get('cinematic') == 'on', encoder=fields.get('encoder', 'h264_nvenc'),
            illustration_lines=lines, steps=steps, image_model=image_model, asr_model=asr_model, alignment_model=alignment_model,
            particle_intensity=float(fields.get('particle_intensity', 1.)),
            particle_speed=float(fields.get('particle_speed', 1.)),
            text_animation=fields.get('text_animation','directed'), audio_mode=fields.get('audio_mode','original'), entrance_effect=fields.get('entrance_effect', 'legacy'), exit_effect=fields.get('exit_effect', 'legacy'),
            type_effect=fields.get('type_effect','mixed'), language=fields.get('language','').strip(),
            ai_model=ai_model, start_step=start_step, project_id=folder.name, run_started=time.time(),
            start_substep=fields.get('start_substep', '') if start_step == 'prompts' and fields.get('start_substep') in PROMPT_STAGES[1:] else '',
            vision_model=fields.get('vision_model','').strip(),auto_verify=fields.get('auto_verify')=='on',
            auto_accept=fields.get('auto_accept')=='on', auto_repair=fields.get('auto_repair','on')=='on',review_threshold=int(fields.get('review_threshold',DEFAULT_THRESHOLD)),
            stage_pictures=fields.get('stage_pictures','ai-painted') or 'ai-painted',
            video_model=fields.get('video_model','').strip() if fields.get('video_generation')=='on' else '')
        config.update(typography_options(fields))
        if config['stage_pictures'] not in ('ai-painted','ai-library','keywords','off'):
            raise ValueError('Invalid 3D stage picture setting')
        if config['artwork_mode'] not in ('cutout','fullscreen','verse','matte'):
            raise ValueError('Invalid artwork mode')
        if config['video_model'] and config['video_model'] not in [m['id'] for m in VIDEO_MODELS]:
            raise ValueError('Choose a supported video model')
        if config['video_model'] and config['artwork_mode'] not in VIDEO_MODES:
            raise ValueError('Video generation needs full-screen or verse-inspired artwork')
        if not 0 <= config['review_threshold'] <= 100:
            raise ValueError('Review threshold must be between 0 and 100 percent')
        if not 0 <= config['particle_intensity'] <= 2:
            raise ValueError('Particle density must be between 0 and 2')
        if config['text_animation'] not in TEXT_ANIMATIONS:
            raise ValueError('Invalid word animation')
        if config['audio_mode'] not in ('original', 'karaoke'):
            raise ValueError('Invalid audio mode')
        catalog = discover_effects()
        validate_choice(config['entrance_effect'], 'entrance', catalog)
        validate_choice(config['exit_effect'], 'exit', catalog)
        config['entrance_pool'] = parse_pool(fields.get('entrance_pool'), 'entrance', catalog)
        config['exit_pool'] = parse_pool(fields.get('exit_pool'), 'exit', catalog)
        if not .2 <= config['particle_speed'] <= 3:
            raise ValueError('Particle speed must be between 0.2 and 3')
        if config['type_effect'] not in EFFECTS:
            raise ValueError('Invalid typography effect')
        if config['auto_verify'] and not config['vision_model']:
            raise ValueError('Select a vision model, or turn off anatomy review for this job')
        if config['encoder'] not in ('h264_nvenc', 'libx264'):
            raise ValueError('Invalid encoder')
        if start_step in ('beginning', 'timing', 'prompts', 'images'):
            # This run makes new artwork, so the gallery starts empty instead of showing the previous images.
            config['gallery_since'] = time.time()
        (folder/'config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')

        if is_restart:
            if start_step == 'timing':
                for f in [folder/'video.timings.json', folder/'video.theme.json', folder/'video.art-times.json']:
                    if f.exists(): f.unlink()
            elif start_step == 'prompts':
                for f in [folder/'video.theme.json']:
                    if f.exists(): f.unlink()
            elif start_step == 'images':
                from artwork.active import archive_images
                archive_images(folder, config)
            elif start_step == 'review':
                pass
            elif start_step == 'render':
                pass

        command = [*module_command('pipeline.cli'), str(audio)]
        if lyrics:
            command.append(str(folder/'lyrics.txt'))
        command += [
            '--theme', config['theme'], '--style-prompt', config['style_prompt'],
            '--image-instructions', config['image_instructions'], '--image-cache', config['image_cache'],
            '--reference-use', config['reference_use'], '--vision-model', config['vision_model'],
            '--artwork-mode', config['artwork_mode'], '--image-seed', str(config['image_seed']),
            '--image-model', config['image_model'], '--image-steps', str(steps), '--illustration-lines', str(lines),
            '--width', str(width), '--height', str(height), '--encoder', config['encoder'], '--preserve-art-slots',
            '--asr-model',config['asr_model'], '--alignment-model',config['alignment_model'],
            '--type-effect',config['type_effect'], '--particle-intensity', str(config['particle_intensity']), '--particle-speed', str(config.get('particle_speed', 1.)),
            '-o', str(folder/'video.mp4')]
        command += ['--text-animation', config['text_animation'], '--audio-mode', config['audio_mode'], '--text-pool',json.dumps(config['text_pool']),
                    '--font-family',config['font_family'],'--font-style',config['font_style'],'--font-scale',str(config['font_scale']),'--lettering-styles',json.dumps(config['lettering_styles']),'--reading-flow',config['reading_flow'],'--kinetic',json.dumps(config['kinetic']),'--effect-speeds',json.dumps(config['effect_speeds']),
                    '--effect-intensities',json.dumps(config['effect_intensities']),
                    '--stage-pictures',config.get('stage_pictures','ai-painted')]
        if config.get('instructions'):
            command += ['--instructions', config['instructions']]
        if not config['auto_accept']:
            command.append('--review-artwork')
        if config['video_model']:
            command += ['--video-model', config['video_model']]
        command += ['--entrance-effect', config['entrance_effect'], '--exit-effect', config['exit_effect']]
        for phase in ('entrance', 'exit'):
            if config[phase + '_pool'] is not None:
                command += ['--' + phase + '-pool', json.dumps(config[phase + '_pool'])]
        if config['language'] and config['language']!='auto':
            command += ['--language',config['language']]
        if ai_model and ai_model != 'auto':
            command += ['--ai-model', ai_model]
        if is_restart:
            command.append('--overwrite')
            design_path = folder/'video.design.json'
            if start_step == 'render' and design_path.exists():
                try:
                    scenes = json.loads(design_path.read_text(encoding='utf-8')).get('scenes')
                    lines = json.loads((folder/'video.timings.json').read_text(encoding='utf-8'))
                    if isinstance(scenes, list) and len(scenes) == len(lines):
                        command += ['--plan', str(design_path)]
                except (OSError, ValueError, AttributeError):
                    pass
            if start_step in ('prompts', 'images', 'review', 'render'):
                timings_path = folder/'video.timings.json'
                if timings_path.exists():
                    command += ['--timings', str(timings_path)]
                    if lyrics:
                        from render.timeline import rewrite_lyrics
                        timed = [line['text'] for line in json.loads(timings_path.read_text(encoding='utf-8'))]
                        submitted = [s for s in (l.strip() for l in lyrics.splitlines()) if s and not re.fullmatch(r'\[.*\]', s)]
                        if len(submitted) == len(timed):
                            (folder/'lyrics.txt').write_text(rewrite_lyrics(lyrics, timed), encoding='utf-8')
            if start_step in ('review', 'render') and (folder/'video.art-times.json').exists():
                command += ['--art-times', str(folder/'video.art-times.json')]
        command += ['--style-reference', *map(str, refs)] if refs else ['--no-default-style-references']
        if config['cinematic']:
            command.append('--cinematic')
        if folder.name in JOBS:
            job = JOBS[folder.name]
            job.config = config
            job.cancelled = False
            job.state['status'] = 'running'
            job.state['percent'] = 0
            job.state['logs'] = []
            job.state['action'] = None
            job.state['dirty'] = []
            job.state['rejected_images'] = []
            job.state['auto_resumes'] = 0
            from artwork.queue import queue_path
            pending_path=queue_path(folder)
            job.state['queued_actions'] = json.loads(pending_path.read_text(encoding='utf-8')) if pending_path.exists() else []
        else:
            job = Job(folder, config)
            JOBS[folder.name] = job
        if audio_replaced:
            job.log('New audio track: lyric timing, vocal and instrument analysis are redone for it.')
        job.save()
        threading.Thread(target=job.run, args=(command,), daemon=True).start()
        return job


def regenerate_new_session(source, image_model=None):
    """Run the whole pipeline with the source job's inputs in a fresh project folder."""
    config = source.config
    fields = {key: json.dumps(value) if isinstance(value, (list, dict)) else str(value)
              for key, value in config.items() if value is not None}
    fields.update(project_id='', start_step='beginning',
                  resolution={(1280, 720): '720p', (1920, 1080): '1080p', (720, 1280): 'portrait'}[
                      (config['width'], config['height'])],
                  cache=config['image_cache'], style=config['theme'], reference_prompt=config['style_prompt'],
                  lines=str(config['illustration_lines']),
                  cinematic='on' if config['cinematic'] else 'off',
                  auto_verify='on' if config['auto_verify'] else 'off',
                  auto_accept='on' if config['auto_accept'] else 'off',
                  auto_repair='on' if config['auto_repair'] else 'off',
                  # The form keeps a video model only with this checkbox on; without it the new run lost its video step.
                  video_generation='on' if config.get('video_model') else 'off',
                  randomize_seed='on' if config.get('randomize_seed') else 'off')
    if image_model is not None:
        from models.image.catalog import model_spec
        if image_model not in {spec['id'] for spec in MODELS}:
            raise ValueError('Choose a supported image model')
        fields['image_model']=image_model
        fields['steps']=str(model_spec(image_model)['steps'])
    audio = Path(config['audio'])
    references = source.folder/'references'
    files = dict(audio=[(config.get('audio_name') or audio.name, audio.read_bytes())],
                 references=[(path.name, path.read_bytes()) for path in sorted(references.iterdir())
                             if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES]
                 if references.is_dir() else [])
    fields['lyrics'] = (source.folder/'lyrics.txt').read_text(encoding='utf-8')
    return start_job(fields, files)


class Handler(BaseHTTPRequestHandler):
    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            self.close_connection = True

    def log_message(self, *args):
        pass

    def respond(self, data, status=200, content_type='application/json'):
        payload = json.dumps(data).encode() if content_type == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        try:
            url = urlsplit(self.path)
            if url.path == '/':
                return self.respond((UI_ROOT/'studio.html').read_bytes(), content_type='text/html; charset=utf-8')
            if url.path == '/assets/default-style-reference.jpg':
                return self.respond((PROJECT_ROOT/'assets'/'default-style-reference.jpg').read_bytes(), content_type='image/jpeg')
            if url.path == '/assets/filipina-reference.png':
                return self.respond((PROJECT_ROOT/'assets'/'filipina-reference.png').read_bytes(), content_type='image/png')
            if url.path in ('/studio.css', '/studio-profiles.js', '/studio-models.js', '/studio-video.js', '/studio-particles.js', '/studio-timeline.js'):
                path = UI_ROOT/url.path.lstrip('/')
                return self.respond(path.read_bytes(), content_type='text/css' if path.suffix=='.css' else 'text/javascript')
            if url.path == '/api/profile-audio':
                from studio.profile_audio import profile_audio_path
                value=parse_qs(url.query).get('path',[''])[0]
                try:
                    path=profile_audio_path(PROJECT_ROOT/'profiles'/'audio',value,AUDIO_SUFFIXES)
                except FileNotFoundError as exc:
                    return self.respond(dict(error=str(exc)),404)
                return self.respond(path.read_bytes(),content_type=mimetypes.guess_type(str(path))[0] or 'application/octet-stream')
            if url.path == '/api/scene-preview':
                from effects.particles.preview import render_scene_preview
                query = parse_qs(url.query)
                scene = query.get('scene', [''])[0]
                if scene not in scene_catalog():
                    raise ValueError('Choose an available scene effect to preview')
                settings=typography_options({key:query[key][0] for key in ('font_family','font_style','font_scale') if key in query})
                return self.respond(render_scene_preview(scene,settings['font_family'],settings['font_style'],settings['font_scale']), content_type='image/gif')
            if url.path == '/api/particle-preview':
                from effects.particles.preview import render_preview
                query = parse_qs(url.query)
                phase = query.get('phase', ['exit'])[0]
                effect = query.get('effect', [''])[0]
                if phase == 'text':
                    from effects.particles.preview import render_text_preview
                    if effect not in TEXT_ANIMATIONS:
                        raise ValueError('Unknown word animation')
                    settings=typography_options({key:query[key][0] for key in ('font_family','font_style','font_scale') if key in query})
                    speed=float(query.get('speed',[1.])[0])
                    if not .2<=speed<=3:raise ValueError('Invalid preview speed')
                    return self.respond(render_text_preview(effect,settings['font_family'],settings['font_style'],settings['font_scale'],speed), content_type='image/gif')
                catalog = discover_effects()
                if phase not in catalog or effect not in catalog[phase]:
                    raise ValueError('Choose an available entrance or exit effect to preview')
                intensity = float(query.get('intensity', [1.])[0])
                speed = float(query.get('speed', [1.])[0])
                if not 0 <= intensity <= 2 or not .2 <= speed <= 3:
                    raise ValueError('Invalid preview intensity or speed')
                settings=typography_options({key:query[key][0] for key in ('font_family','font_style','font_scale') if key in query})
                return self.respond(render_preview(catalog[phase][effect],phase,intensity,speed,settings['font_family'],settings['font_style'],settings['font_scale']), content_type='image/gif')
            if url.path == '/api/job-list':
                return self.respond(dict(jobs=job_list()))
            if url.path == '/api/config':
                from models.gpu.presets import PRESETS; from models.ollama.catalog import PROMPT_MODELS, VISION_MODELS
                return self.respond(dict(token=TOKEN, image_instructions_supported=True, auto_accept_supported=True, new_session_regeneration_supported=True, particle_materials_version=13, ai_typography_supported=True, typography_controls_supported=True, word_animations_supported=True, video_history_supported=True, video_history_version=2, live_artwork_version=2, replacement_priority_supported=True, particle_effects=catalog_choices(), scene_effects=list(scene_catalog().values()), prompt_regeneration=True, generation_queue_version=2, style_prompt=STYLE_PROMPT, model=MODEL, image_models=MODELS, video_models=VIDEO_MODELS, model_presets=PRESETS, prompt_choices=PROMPT_MODELS, vision_choices=VISION_MODELS, asr_models=ASR_MODELS, vocal_languages=LANGUAGES, default_asr=DEFAULT_ASR,
                    jobs=job_list()))
            if url.path == '/api/gpu':
                from models.gpu.telemetry import gpu_usage
                return self.respond(gpu_usage())
            if url.path == '/api/downloads':
                from models.downloads import download_status
                return self.respond(download_status())
            if url.path in ('/api/models','/api/models/best'):
                from models.ollama.catalog import model_choices
                from models.ollama.service import local_json
                return self.respond(model_choices(local_json,review=parse_qs(url.query).get('review',['1'])[0]!='0'))
            if url.path.startswith('/api/projects/') and url.path.endswith('/status'):
                project_id = url.path.split('/')[3]
                folder = ROOT / project_id
                if not folder.is_dir():
                    return self.respond(dict(exists=False), 404)
                manifests = (list((folder / 'video.artwork').glob('*/illustrations.json')) +
                             list((folder / 'video.artwork').glob('illustrations.json')) +
                             list(folder.glob('illustrations.json')))
                from artwork.active import select_manifest
                try:manifest=select_manifest(folder)
                except ValueError:
                    manifest=next((p for p in manifests if p.parent in (folder,folder/'video.artwork')),None)
                images, reviews = [], []
                if manifest and manifest.parent.is_dir():
                    images = [p.name for p in manifest.parent.glob('[0-9][0-9][0-9].png') if not p.name.endswith('.raw.png')]
                    reviews = [p.name for p in manifest.parent.glob('*.review.json')]
                if not images and manifest and manifest.parent in (folder,folder/'video.artwork'):
                    images = [p.name for p in (folder / 'video.artwork').glob('*/*.png') if not p.name.endswith(('.raw.png', '.plate.png'))]
                if not reviews and manifest and manifest.parent in (folder,folder/'video.artwork'):
                    reviews = [p.name for p in (folder / 'video.artwork').glob('*/*.review.json')]
                has_timings = (folder / 'video.timings.json').exists()
                has_prompts = bool(manifest and manifest.exists())
                has_video = (folder / 'video.mp4').exists()
                current_step = 5 if has_video else 4 if reviews else 3 if images else 2 if has_prompts else 1 if has_timings else 0
                from direction.prompt_checkpoint import restartable
                prompt_substeps = restartable(folder/'video.artwork') if has_timings and (folder/'video.artwork').is_dir() else []
                return self.respond(dict(prompt_substeps=prompt_substeps,
                    exists=True, id=project_id,
                    has_audio=bool(list(folder.glob('audio.*'))),
                    has_lyrics=(folder / 'lyrics.txt').exists(),
                    has_timings=has_timings,
                    has_prompts=has_prompts,
                    has_images=bool(images),
                    image_count=len(images),
                    has_reviews=bool(reviews),
                    has_video=has_video,
                    current_step=current_step
                ))
            if url.path.startswith('/api/jobs/') and url.path.endswith('/timeline'):
                job = JOBS.get(url.path.split('/')[3])
                if job is None:
                    return self.respond(dict(error='This song is no longer loaded in the studio. Reload the page and choose it again.'), 404)
                from studio.timeline_data import song_duration, timeline_stems, word_timings
                duration = song_duration(job.folder, job.config['audio'])
                # Timing failed or never finished: open on a draft the user can place by hand and save.
                draft = not (job.folder/'video.timings.json').is_file()
                timings = word_timings(job.folder, duration)
                stems = timeline_stems(job.folder)
                from artwork.video_art import artwork_lane
                try:
                    lanes = [dict(index=lane['index'], start=lane['start'], end=lane['end'], image=job.url(lane['image']),
                                  video=job.url(lane['video']) if lane['video'] else None, offset=lane['offset'],
                                  framing=lane['framing'],
                                  length=lane['length']) for lane in artwork_lane(job.folder, job.config, timings, duration)
                             if lane['image'].is_file()]
                except (OSError, ValueError, KeyError, IndexError):
                    lanes = []
                return self.respond(dict(timings=timings, stems=stems, duration=duration, artwork=lanes,
                                         frame=dict(width=job.config.get('width', 1920), height=job.config.get('height', 1080)),
                                         audio=job.url(Path(job.config['audio'])), draft=draft,
                                         needs_render=job.state.get('timing_dirty', False)))
            if url.path.startswith('/api/jobs/'):
                job = JOBS[url.path.split('/')[3]]
                cursor = max(0, int(parse_qs(url.query).get('cursor', [0])[0]))
                return self.respond(job.snapshot(cursor))
            if url.path.startswith('/files/'):
                _, _, job_id, relative = unquote(url.path).split('/', 3)
                job = JOBS[job_id]
                path = (job.folder/relative).resolve()
                valid=path.is_relative_to(job.folder.resolve()) and path.is_file() and path.suffix.lower() in {'.png', '.mp4', '.txt', '.json', *AUDIO_SUFFIXES}
                if not valid:
                    return self.respond(dict(error='File not found'), 404)
                size, start, end = path.stat().st_size, 0, path.stat().st_size-1
                request_range = self.headers.get('Range', '')
                match = re.fullmatch(r'bytes=(\d+)-(\d*)', request_range)
                if match:
                    start = int(match[1]); end = min(end, int(match[2])) if match[2] else end
                if start > end or start >= size:
                    return self.respond(dict(error='Invalid range'), 416)
                self.send_response(206 if match else 200)
                self.send_header('Content-Type', mimetypes.guess_type(str(path))[0] or 'application/octet-stream')
                self.send_header('Content-Length', str(end-start+1))
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('X-Content-Type-Options', 'nosniff')
                if match:
                    self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                self.end_headers()
                with path.open('rb') as source:
                    source.seek(start)
                    remaining = end-start+1
                    while remaining:
                        chunk = source.read(min(1024*1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk); remaining -= len(chunk)
                return
            self.respond(dict(error='Not found'), 404)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            self.close_connection = True
        except (KeyError, ValueError, OSError) as exc:
            self.respond(dict(error=str(exc)), 400)
        except Exception as exc:
            self.respond(dict(error=str(exc)), 503)

    def do_POST(self):
        try:
            if self.headers.get('X-Studio-Token') != TOKEN:
                return self.respond(dict(error='Reload the studio page'), 403)
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= 256*1024*1024:
                raise ValueError('Upload must be between 1 byte and 256 MiB')
            body = self.rfile.read(length)
            route = urlsplit(self.path).path
            if route in ('/api/downloads','/api/downloads/cancel'):
                from models.downloads import request_downloads, cancel_downloads
                args=json.loads(body)
                return self.respond(cancel_downloads(args.get('ids',[])) if route.endswith('/cancel') else request_downloads(args.get('models',[])))
            if route == '/api/profile-audio':
                from studio.profile_audio import store_profile_audio
                fields,files=parse_form(body,self.headers['Content-Type'])
                if len(files.get('audio',[]))!=1:
                    raise ValueError('Choose one audio file')
                name,content=files['audio'][0]
                path=store_profile_audio(PROJECT_ROOT/'profiles'/'audio',name,content,AUDIO_SUFFIXES)
                return self.respond(dict(path=str(path)),201)
            if route == '/api/import-youtube':
                from studio.youtube_import import import_youtube
                args=json.loads(body)
                return self.respond(import_youtube(args.get('url',''), PROJECT_ROOT/'profiles'/'audio'),201)
            if route == '/api/jobs':
                fields, files = parse_form(body, self.headers['Content-Type'])
                return self.respond(dict(id=start_job(fields, files).folder.name), 201)
            _, _, _, job_id, operation = route.split('/')
            job = JOBS[job_id]
            # A stopped job (cancelled or failed at any step) that still has a finished video from an earlier render
            # can be edited and rebuilt like a completed one.
            saved_video = (job.state['status'] in ('cancelled', 'failed') and not job.state.get('action')
                           and (job.folder/'video.mp4').is_file())
            if operation == 'regenerate-new':
                args=json.loads(body)
                if not isinstance(args,dict) or not args.get('image_model'):
                    raise ValueError('Reload the studio page to apply the selected image model')
                return self.respond(dict(id=regenerate_new_session(job,args.get('image_model')).folder.name), 201)
            if operation == 'cancel':
                stop_job(job)
                return self.respond(dict(ok=True))
            if self.headers.get('Content-Type', '').startswith('multipart/'):
                args, files = parse_form(body, self.headers['Content-Type'])
            else:
                args, files = json.loads(body), {}
            if operation == 'keep-picture':  # a preference for the next render; allowed at any time
                if not isinstance(args.get('key'), str) or len(args['key']) > 40:
                    raise ValueError('Invalid picture')
                from direction.ornaments import set_picture_kept
                set_picture_kept(job.folder, args['key'], bool(args.get('keep', True)))
                return self.respond(dict(ok=True))
            if operation == 'clip-start':
                from artwork.video_art import sidecar, offset_path, clip_duration, clip_settings, checked_framing
                index = int(args.get('index', -1))
                manifest = job.manifest()
                if not 0 <= index < len(json.loads(manifest.read_text(encoding='utf-8'))['prompts']):
                    raise ValueError('Invalid illustration index')
                image = manifest.parent/f'{index:03d}.png'
                clip = sidecar(image)
                if clip is None:
                    raise ValueError('This illustration is not a video clip')
                settings = clip_settings(image)
                if 'offset' in args:
                    offset = float(args['offset'])
                    length = clip_duration(clip)
                    if not 0 <= offset or (length and offset >= length):
                        raise ValueError('The clip start must fall inside the clip')
                    settings['offset'] = round(offset, 3)
                if 'framing' in args:
                    settings['framing'] = {k: round(v, 4) for k, v in checked_framing(args['framing']).items()}
                offset = float(settings.get('offset', 0.))
                offset_path(image).write_text(json.dumps(settings), encoding='utf-8')
                with LOCK:
                    if (job.folder/'video.mp4').exists() and index not in job.state['dirty']:
                        job.state['dirty'].append(index)
                    job.log(f'Illustration {index+1} video '+('framing saved' if 'framing' in args else f'now starts {offset:.2f}s into the clip')
                            +'; rebuild changed images to apply.')
                    job.save()
                return self.respond(dict(ok=True))
            if operation == 'timings':
                from pipeline.timing import validate
                from studio.timeline_data import song_duration, timeline_stems, word_timings
                current_path = job.folder/'video.timings.json'
                updated = args.get('timings')
                if not isinstance(updated, list):
                    raise ValueError('Supply lyric word timings')
                duration = song_duration(job.folder, job.config['audio'])
                draft = not current_path.is_file()
                if draft and (job.state['status'] == 'running' or job.state.get('action')):
                    raise ValueError('Step 1: Timing is still running for this song; wait for it to finish or stop it first.')
                current = word_timings(job.folder, duration)
                validate(updated, [line['text'] for line in current], duration)
                if [[word['text'] for word in line['words']] for line in updated] != [[word['text'] for word in line['words']] for line in current]:
                    raise ValueError('The timeline editor can change timing, not lyric text')
                # A video still being made would finish with the old timings: stop it, save, and start it again.
                restart = stop_video_work(job) if video_busy(job) else None
                backup = job.folder/'video.timings.before-editor.json'
                if not backup.exists() and not draft:
                    shutil.copy2(current_path, backup)
                temporary = job.folder/'video.timings.editing.json'
                temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding='utf-8')
                temporary.replace(current_path)
                if draft:
                    job.log('Word timings placed by hand in the timeline; restart from Step 2: Prompts to continue with them.')
                    job.save()
                    return self.respond(dict(ok=True, draft=True))
                job.state['timing_dirty'] = True
                if restart:
                    restart_video_work(job, *restart)
                    return self.respond(dict(ok=True, restarted=restart[0]))
                job.log('Word timings edited in the timeline; rebuild the video to apply them.')
                job.save()
                return self.respond(dict(ok=True))
            if operation in ('regenerate','reprompt') and (not isinstance(args.get('prompt',''),str) or len(args.get('prompt',''))>32768):
                raise ValueError('The generation prompt must be text no longer than 32,768 characters')
            if operation in ('regenerate','reprompt') and (not isinstance(args.get('style',''),str) or len(args.get('style',''))>4000):
                raise ValueError('The art style must be text no longer than 4,000 characters')
            with LOCK:
                if saved_video:
                    job.cancelled = False
                    job.state['status'] = 'complete'
                if operation in ('regenerate','reprompt') and (job.state['status'] == 'running' or job.state['action']):
                    if not args.get('image_model'):
                        raise ValueError('Reload the studio page to apply the selected image model')
                    index = int(args.get('index', -1))
                    count = len(json.loads(job.manifest().read_text(encoding='utf-8'))['prompts'])
                    if not 0 <= index < count:
                        raise ValueError('Invalid illustration index')
                    job.queue_generation(index,operation,str(args.get('prompt','')),str(args.get('model') or job.config.get('ai_model','auto')),args.get('image_model'),args.get('style'),args.get('steps'))
                    job.log(f'Illustration {index+1} regeneration queued for the next GPU review pause.')
                    job.save()
                    return self.respond(dict(ok=True, queued=True))
                if operation == 'verify' and job.state['action'] and job.state['status'] in ('review', 'complete'):
                    # Like regeneration, a Verify of the selected image waits in the queue behind the running operation.
                    if not args.get('model'):
                        raise ValueError('Choose an installed Ollama vision model')
                    index = int(args.get('index', -1))
                    if not 0 <= index < len(json.loads(job.manifest().read_text(encoding='utf-8'))['prompts']):
                        raise ValueError('Invalid illustration index')
                    threshold = args.get('review_threshold', job.config.get('review_threshold', DEFAULT_THRESHOLD))
                    if type(threshold) is not int or not 0 <= threshold <= 100:
                        raise ValueError('Review threshold must be an integer from 0 to 100')
                    job.config.update(review_threshold=threshold, auto_repair=bool(args.get('auto_repair', job.config.get('auto_repair', True))))
                    (job.folder/'config.json').write_text(json.dumps(job.config, indent=2), encoding='utf-8')
                    if not any(a.get('action') == 'verify' and a.get('index') == index for a in job.state['queued_actions']):
                        edited = {k: ' '.join(str(args[k]).split()) if k == 'style' else str(args[k]).strip()
                                  for k in ('prompt', 'style') if isinstance(args.get(k), str) and args[k].strip()}
                        if 'prompt' in edited:edited['user_prompt'] = edited.pop('prompt')
                        job.state['queued_actions'].append(dict(action='verify', index=index, model=args['model'], **edited))
                        job.log(f'Illustration {index+1} review queued after the current image operation.')
                    job.save()
                    return self.respond(dict(ok=True, queued=True))
                if job.state['action'] and not (operation in ('select','replace') and job.state['action'] in ('verify','regenerate')):
                    raise ValueError('Wait for the current image operation to finish')
                live_selection = (operation in ('select', 'replace') and job.state['status'] == 'running'
                                  and job.state['stage'] in ('illustrations','cutouts','verification','repair','repair-complete','direction','render'))
                saved_review = (operation == 'skip-verify' and job.state['status'] == 'cancelled'
                                and job.state['stage'] == 'review')
                if job.state['status'] not in ('review', 'complete') and not saved_video and not live_selection and not saved_review:
                    raise ValueError('Images can be changed at artwork review or after the video completes')
                if any(other is not job and (other.state['status'] in ('queued', 'running', 'review') or other.state['action']) for other in JOBS.values()):
                    raise ValueError('Another job is active; finish or cancel it first')
                if operation in ('approve','rebuild','rerender','patch'):
                    failures=job.rejected_selections()
                    if failures:
                        numbers=', '.join(str(i+1) for i in failures)
                        raise ValueError(f'Illustrations {numbers} are below the review threshold. Regenerate or replace them, or change the threshold and review again.')
                if operation == 'approve':
                    if job.state['queued_actions']:
                        raise ValueError('Wait for queued image regenerations to finish')
                    if job.state['status'] != 'review':
                        raise ValueError('This job is not waiting for review')
                    job.state.update(status='running', message='Artwork approved; continuing render', dirty=[])
                    from artwork.queue import replacement_review_path
                    replacement_review_path(job.folder).unlink(missing_ok=True)
                    (job.folder/'artwork-approved').touch()
                    return self.respond(dict(ok=True))
                if operation in ('verify','verify-all') and 'review_threshold' in args:
                    threshold=args['review_threshold']
                    if type(threshold) is not int or not 0 <= threshold <= 100:
                        raise ValueError('Review threshold must be an integer from 0 to 100')
                    if type(args.get('auto_repair')) is not bool:
                        raise ValueError('Automatic repair must be true or false')
                    job.config.update(review_threshold=threshold,auto_repair=args['auto_repair'])
                    (job.folder/'config.json').write_text(json.dumps(job.config,indent=2),encoding='utf-8')
                if operation == 'verify-all':
                    if not args.get('model'):
                        raise ValueError('Choose an installed vision model first')
                    job.queue_reviews(args['model'])
                    job.start_next()
                    job.save()
                    return self.respond(dict(ok=True,queued=True))
                if operation == 'rerender':
                    if (job.state['status'] != 'complete' and not saved_video) or job.state['queued_actions']:
                        raise ValueError('Wait for the current video and queued operations to finish')
                    if saved_video:
                        job.cancelled = False
                        job.state['status'] = 'complete'
                    effect = args.get('type_effect', job.config.get('type_effect','none'))
                    density = float(args.get('particle_intensity', job.config.get('particle_intensity',1.)))
                    if effect not in EFFECTS or not 0 <= density <= 2:
                        raise ValueError('Choose a valid letter effect and particle density')
                    speed = float(args.get('particle_speed', job.config.get('particle_speed', 1.)))
                    if not .2 <= speed <= 3:
                        raise ValueError('Particle speed must be between 0.2 and 3')
                    catalog = discover_effects()
                    entrance = args.get('entrance_effect', job.config.get('entrance_effect', 'legacy'))
                    exit_effect = args.get('exit_effect', job.config.get('exit_effect', 'legacy'))
                    if 'entrance_effect' in args:
                        validate_choice(entrance, 'entrance', catalog)
                    if 'exit_effect' in args:
                        validate_choice(exit_effect, 'exit', catalog)
                    entrance_pool = parse_pool(args.get('entrance_pool', job.config.get('entrance_pool')), 'entrance', catalog, strict='entrance_pool' in args)
                    exit_pool = parse_pool(args.get('exit_pool', job.config.get('exit_pool')), 'exit', catalog, strict='exit_pool' in args)
                    text_animation = args.get('text_animation', job.config.get('text_animation','directed'))
                    if text_animation not in TEXT_ANIMATIONS:
                        raise ValueError('Invalid word animation')
                    audio_mode = args.get('audio_mode', job.config.get('audio_mode', 'original'))
                    if audio_mode not in ('original', 'karaoke'):
                        raise ValueError('Invalid audio mode')
                    typography = typography_options(dict(job.config,**args))
                    pictures = args.get('stage_pictures') or job.config.get('stage_pictures','ai-painted')
                    if pictures not in ('ai-painted','ai-library','keywords','off'):
                        raise ValueError('Invalid 3D stage picture setting')
                    job.config.update(**typography,text_animation=text_animation, audio_mode=audio_mode, entrance_pool=entrance_pool, exit_pool=exit_pool, type_effect=effect, particle_intensity=density, particle_speed=speed,
                                      entrance_effect=entrance, exit_effect=exit_effect, stage_pictures=pictures)
                    (job.folder/'config.json').write_text(json.dumps(job.config, indent=2), encoding='utf-8')
                    command = [*module_command('studio.worker'), 'rerender', str(job.folder)]
                    job.state.update(action='rerender', action_percent=0, message='Rebuilding video with selected letter effects')
                    threading.Thread(target=job.run, args=(command, 'rerender'), daemon=True).start()
                    return self.respond(dict(ok=True))
                if operation == 'rebuild':
                    from studio.video_versions import verified_changes
                    changes, verified = verified_changes(job.folder, job.state['dirty'])
                    if verified:job.state['dirty'] = changes
                    if job.state['status'] != 'complete' and not saved_video:
                        raise ValueError('Rebuild is available after the first video completes')
                    if saved_video:
                        job.cancelled = False
                        job.state['status'] = 'complete'
                    job.state['queued_actions'].extend(dict(action='patch', index=i) for i in job.state['dirty'])
                    job.start_next()
                    job.save()
                    return self.respond(dict(ok=True, queued=True))
                index = int(args.get('index', -1))
                manifest = job.manifest()
                count = len(json.loads(manifest.read_text(encoding='utf-8'))['prompts'])
                if not 0 <= index < count:
                    raise ValueError('Invalid illustration index')
                target = manifest.parent/f'{index:03d}.png'
                if operation == 'skip-verify':
                    selected = checked_file(job, args['path'])
                    if selected != target or not target.is_file():
                        raise ValueError('Only the selected illustration can skip verification')
                    from filelock import FileLock
                    with FileLock(str(target)+'.write.lock',timeout=30):
                        fingerprint = hashlib.sha256(target.read_bytes()).hexdigest()
                        report_path = target.with_suffix('.review.json')
                        try: previous = json.loads(report_path.read_text(encoding='utf-8'))
                        except (OSError, ValueError): previous = {}
                        if not previous.get('validation_pending') or previous.get('image_sha256') != fingerprint:
                            raise ValueError('Only a pending validation for this image can be skipped')
                        report = dict(model=previous.get('model'), manual_skip=True, validation_pending=False,
                            score=None, rejected=False, verdict='skipped',
                            summary='Verification skipped manually. Inspect this image before approving artwork.',
                            issues=[], hand_checks=[], uncertain=True, image_sha256=fingerprint,
                            image=str(target), reviewed_at=time.time(), advisory=True)
                        report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
                    job.log(f'Illustration {index+1} verification skipped manually.')
                    job.save()
                    return self.respond(dict(ok=True))
                if operation in ('select', 'replace'):
                    if operation == 'replace':
                        name, content = files['replacement'][0]
                        from artwork.video_art import VIDEO_SUFFIXES, import_clip
                        candidate = job.folder/'candidates'/f'{index:03d}'/str(time.time_ns())
                        if Path(name).suffix.lower() in VIDEO_SUFFIXES:
                            candidate.mkdir(parents=True, exist_ok=True)
                            upload = candidate/('upload'+Path(name).suffix.lower())
                            upload.write_bytes(content)
                            try:selected = import_clip(upload, candidate)
                            finally:upload.unlink(missing_ok=True)
                        else:
                            selected = store_image(candidate, name, content)
                    else:
                        selected = checked_file(job, args['path'])
                        report=selected.with_suffix('.review.json')
                        if report.exists():
                            review=json.loads(report.read_text(encoding='utf-8'))
                            if review.get('image_sha256')==hashlib.sha256(selected.read_bytes()).hexdigest() and rejected(review,job.config.get('review_threshold',DEFAULT_THRESHOLD)):
                                raise ValueError('This candidate is below the quality threshold; choose another image or review with a different threshold')
                    if selected != target and (not target.exists() or selected.read_bytes() != target.read_bytes()):
                        versions = job.folder/'versions'/f'{index:03d}'
                        versions.mkdir(parents=True, exist_ok=True)
                        if target.exists():
                            from artwork.metadata import variant_metadata
                            archived=versions/f'{time.time_ns()}.png';shutil.copy2(target,archived)
                            from artwork.video_art import copy_slot_clip
                            copy_slot_clip(target,archived)
                            archive_job=json.loads(manifest.read_text(encoding='utf-8'))
                            archived.with_suffix('.artwork.json').write_text(json.dumps(variant_metadata(target,archive_job,index)),encoding='utf-8')
                        from filelock import FileLock
                        with FileLock(str(target)+'.write.lock',timeout=30):
                            temporary=target.with_suffix('.selected.tmp.png')
                            shutil.copy2(selected,temporary)
                            temporary.replace(target)
                            from artwork.video_art import copy_slot_clip
                            copy_slot_clip(selected,target)
                            target.with_suffix('.selection.json').write_text(json.dumps(dict(selected=str(selected),time=time.time())),encoding='utf-8')
                            candidate_review=selected.with_suffix('.review.json')
                            try:chosen_report=json.loads(candidate_review.read_text(encoding='utf-8'))
                            except (OSError,ValueError):chosen_report={}
                            if chosen_report.get('image_sha256')==hashlib.sha256(target.read_bytes()).hexdigest():
                                chosen_report['image']=str(target)
                                target.with_suffix('.review.json').write_text(json.dumps(chosen_report,indent=2),encoding='utf-8')
                            else:target.with_suffix('.review.json').unlink(missing_ok=True)
                            from artwork.metadata import variant_metadata, select_metadata
                            selection_job=json.loads(manifest.read_text(encoding='utf-8'))
                            select_metadata(manifest,index,variant_metadata(selected,selection_job,index))
                        if (job.folder/'video.mp4').exists() and index not in job.state['dirty']:
                            job.state['dirty'].append(index)
                    job.log(f'Illustration {index+1} selected. '+('Rebuild this section to update the video.' if (job.folder/'video.mp4').exists() else 'Selection will be used in the render.'))
                    job.queue_missing_clips()
                    job.save()
                    job.start_next()
                    return self.respond(dict(ok=True))
                if operation in ('regenerate','reprompt'):
                    if not args.get('image_model'):
                        raise ValueError('Reload the studio page to apply the selected image model')
                    job.queue_generation(index,operation,str(args.get('prompt','')),str(args.get('model') or job.config.get('ai_model','auto')),args.get('image_model'),args.get('style'),args.get('steps'))
                    job.start_next();job.save()
                    return self.respond(dict(ok=True,queued=True))
                if operation not in ('regenerate', 'verify', 'patch'):
                    raise ValueError('Unknown operation')
                if operation == 'patch' and job.state['status'] != 'complete':
                    raise ValueError('Section rebuild is available after the video completes')
                command = [*module_command('studio.worker'), operation, str(job.folder), '--index', str(index)]
                if operation == 'verify':
                    if not args.get('model'):
                        raise ValueError('Choose an installed Ollama vision model')
                    selected = checked_file(job, args['path'])
                    command += ['--model', args['model'], '--candidate', str(selected)]
                    if isinstance(args.get('prompt'), str) and args['prompt'].strip():
                        command += ['--prompt', args['prompt'][:32768], '--style', str(args.get('style', ''))[:4000]]
                if operation == 'regenerate':
                    command += ['--prompt', str(args.get('prompt', ''))[:5000]]
                job.repaired_now = set()
                job.state.update(action=operation, action_percent=0, message=f'Starting {operation}')
                threading.Thread(target=job.run, args=(command, operation), daemon=True).start()
                return self.respond(dict(ok=True))
        except (ValueError, KeyError, OSError, IndexError) as exc:
            self.respond(dict(error=str(exc)), 400)
        except ImportError as exc:
            # Answer instead of dropping the connection, which the browser only reports as "Failed to fetch".
            package = {'yt_dlp': 'yt-dlp', 'bs4': 'beautifulsoup4'}.get(exc.name, exc.name)
            self.respond(dict(error=f'The studio Python environment is missing the "{package}" package. '
                                    f'Install it with: python -m pip install -r requirements.txt, then restart the studio.'), 500)


def job_list():
    """Every song, newest first, with its run status so a fresh window can open the one that is running."""
    return [dict(id=j.folder.name, name=j.config['name'], status=j.state.get('status', ''))
            for j in reversed(list(JOBS.values()))]


def restore():
    ROOT.mkdir(parents=True, exist_ok=True)
    for folder in sorted(ROOT.iterdir()):
        if (folder/'config.json').exists():
            try:
                job = Job(folder, json.loads((folder/'config.json').read_text(encoding='utf-8')))
                if (folder/'state.json').exists():
                    job.state.update(json.loads((folder/'state.json').read_text(encoding='utf-8')))
                if job.state['status'] not in ('complete', 'failed', 'cancelled'):
                    job.state.update(status='cancelled', message='Server restarted; previous job interrupted', finished=time.time())
                job.state['action'] = None
                job.state['queued_actions'] = []
                job.state['active_images'] = []
                from artwork.queue import queue_path
                pending_path=queue_path(folder)
                if pending_path.exists():
                    job.state['queued_actions']=json.loads(pending_path.read_text(encoding='utf-8'))
                JOBS[folder.name] = job
            except (OSError, ValueError):
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    restore()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    url = f'http://127.0.0.1:{args.port}'
    print(f'Kinetic Lyrics: {url}\nOutputs: {ROOT}\nPress Ctrl+C to stop.', flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for job in JOBS.values():
            if job.state['status'] in ('queued', 'running', 'review') or job.state['action']:
                stop_job(job)
        server.server_close()


if __name__ == '__main__':
    main()
