"""Local-only lyric studio. No web framework or extra UI dependencies required."""
from typography_settings import typography_options
from project_paths import PROJECT_ROOT, UI_ROOT, default_model_cache, studio_output
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

from kinetic_illustrations import MODEL, STYLE_PROMPT
from kinetic_progress import PREFIX
from kinetic_effects import EFFECTS, TEXT_ANIMATIONS
from particle_catalog import discover_effects, catalog_choices, validate_choice, parse_pool
from image_models import MODELS
from review_policy import rejected, DEFAULT_THRESHOLD
from speech_models import ASR_MODELS, LANGUAGES, DEFAULT_ASR, validate_speech

HERE = Path(__file__).resolve().parent
ROOT = studio_output(PROJECT_ROOT,'lyric-studio')
STAGES = {'alignment': (0, 10), 'subjects': (10, 15), 'model': (15, 20),
          'illustrations': (20, 70), 'cutouts': (70, 80), 'review': (80, 80),
          'direction': (80, 85), 'render': (85, 99), 'complete': (100, 100)}
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
                from active_artwork import record_manifest
                candidate=Path(artifact)
                if candidate.name!='illustrations.json':candidate=candidate.parent/'illustrations.json'
                active=record_manifest(candidate) if candidate.resolve().is_relative_to((self.folder/'video.artwork').resolve()) else None
                if active:self.state['active_manifest']=active
            if event['stage']=='queue-claimed':
                requests=event.get('requests',[]);claimed={i.get('request_id') for i in requests}
                self.state['queued_actions']=[i for i in self.state['queued_actions'] if i.get('request_id') not in claimed]
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

    def queue_generation(self,index,operation,prompt,model):
        from generation_queue import update_queue
        item=dict(request_id=secrets.token_hex(12),action=operation,index=index,prompt=prompt,model=model)
        position=next((i for i,a in enumerate(self.state['queued_actions']) if a.get('action')=='verify'),len(self.state['queued_actions']))
        self.state['queued_actions'].insert(position,item)
        update_queue(self.folder,append=item)

    def start_next(self):
        """Batch prompt work before image work, and image work before reviews."""
        with LOCK:
            if self.cancelled or self.state['action'] or self.state['status'] not in ('review','complete') or not self.state['queued_actions']:
                return
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
                from generation_queue import update_queue
                update_queue(self.folder,remove=[i.get('request_id') for i in batch])
            if generation and any(i.get('action')=='reprompt' for i in batch):operation='reprompt'
            command=[sys.executable,'-u',str(HERE/'studio_worker.py'),operation,str(self.folder),'--index',str(item['index'])]
            if operation in ('verify','repair'):
                command+=['--model',item['model']]
                if operation=='repair':command+=['--expected-sha',item['expected_sha']]
            elif operation=='regenerate':command+=['--prompt',item.get('prompt','')]
            if len(batch)>1 or operation=='reprompt':
                batch_path=self.folder/f'actions-{time.time_ns()}.json'
                batch_path.write_text(json.dumps(batch),encoding='utf-8');command+=['--batch',str(batch_path)]
            self.state.update(action=operation,action_percent=0,active_images=[i['index'] for i in batch] if generation else [],
                              action_stage='subjects' if operation=='reprompt' else 'model',message=f'{operation.capitalize()} batch starting')
            threading.Thread(target=self.run,args=(command,operation),daemon=True).start()

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
        try:
            env = dict(os.environ, PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8', KINETIC_PROGRESS='1')
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
                    if code:
                        if action == 'patch':
                            self.state['queued_actions'] = [a for a in self.state['queued_actions'] if a.get('action') != 'patch']
                        self.log(f'{action} failed (exit {code}). See errors above.', 'error')
                    elif action == 'rerender':
                        self.state['dirty'] = []
                        self.state['timeline_dirty'] = False
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
                        at=float(timings[0]['words'][0]['start'])+.35
                        subprocess.run(['ffmpeg','-v','error','-y','-ss',str(at),'-i',str(self.folder/'video.mp4'),
                            '-frames:v','1',str(self.folder/'poster.png')],check=True,capture_output=True)
                    except (OSError,ValueError,KeyError,IndexError,subprocess.CalledProcessError):
                        self.log('Preview poster could not be created; the video is still available.','warning')
                if not code and (not action or action in ('patch','rerender')):
                    from video_versions import verified_changes
                    dirty, verified = verified_changes(self.folder, self.state['dirty'])
                    if verified:self.state['dirty'] = dirty
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

    def resume_command(self, command):
        """The same run, resumed from saved work: timings, artwork, approval and a plan made by this run."""
        command=[part for part in command if part != '--overwrite']+['--overwrite']
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
        threading.Thread(target=self.resume_later,args=(self.resume_command(command),),daemon=True).start()
        return True

    def resume_later(self, command):
        time.sleep(AUTO_RESUME_DELAY)
        with LOCK:
            if self.cancelled:
                self.state.update(status='cancelled',message='Cancelled; saved files retained',finished=time.time());self.save()
                return
        self.run(command)

    def save(self):
        (self.folder/'state.json').write_text(json.dumps(self.state), encoding='utf-8')

    def snapshot(self, cursor=0):
        with LOCK:
            result = copy.deepcopy(self.state)
        from video_versions import verified_changes, video_versions
        result['dirty'], result['dirty_verified'] = verified_changes(self.folder, result.get('dirty', []))
        result['video_versions'] = video_versions(self.folder, self.url)
        from generation_queue import replacement_review_path
        try:
            waiting=json.loads(replacement_review_path(self.folder).read_text(encoding='utf-8'))
            result['replacement_review']=[c['index'] for c in waiting.get('candidates',[])] if waiting.get('manifest')==str(self.manifest()) else []
        except (OSError,ValueError):result['replacement_review']=[]
        logs = result.pop('logs')
        result.update(logs=logs[cursor:], cursor=len(logs), images=self.images(), rejected_images=self.rejected_selections(),
                      elapsed=round(self.state.get('finished', time.time())-self.state['started']),
                      render_settings=dict(**typography_options(self.config),text_animation=self.config.get('text_animation','directed'), auto_accept=self.config.get('auto_accept',False), type_effect=self.config.get('type_effect','none'), entrance_effect=self.config.get('entrance_effect','legacy'), exit_effect=self.config.get('exit_effect','legacy'), entrance_pool=self.config.get('entrance_pool'), exit_pool=self.config.get('exit_pool'), particle_speed=self.config.get('particle_speed',1.), particle_intensity=self.config.get('particle_intensity',1.)))
        if (self.folder/'video.mp4').exists():
            result['video'] = self.url(self.folder/'video.mp4')
        if (self.folder/'poster.png').exists():
            result['poster'] = self.url(self.folder/'poster.png')
        return result

    def url(self, path):
        from urllib.parse import quote
        return '/files/'+self.folder.name+'/'+quote(path.relative_to(self.folder).as_posix())+'?v='+str(path.stat().st_mtime_ns)

    def timeline(self):
        """Everything the timeline editor draws: words, illustrations and the audio stems."""
        from timeline import ART_TIMES, illustration_starts, load_art_times, stem_sources, tighten_line_starts
        data = json.loads((self.folder/'video.timings.json').read_text(encoding='utf-8'))
        duration = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', self.config['audio']], text=True))
        art = []
        try:
            manifest = self.manifest()
            job = json.loads(manifest.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            manifest, job = None, None
        if job:
            cues = [line['words'][0]['start'] for line in tighten_line_starts(copy.deepcopy(data))]
            groups = job.get('line_groups')
            if groups is not None and len(groups) != len(job['prompts']):
                groups = None
            defaults = illustration_starts(cues, len(job['prompts']), self.config.get('illustration_lines', 2), 1., groups)
            saved = load_art_times(self.folder/ART_TIMES)
            custom = saved if saved is not None and len(saved) == len(defaults) else None
            for i, start in enumerate(defaults):
                image = manifest.parent/f'{i:03d}.png'
                art.append(dict(index=i, start=custom[i] if custom else start, default_start=start,
                                lyrics=job['groups'][i] if i < len(job.get('groups', [])) else '',
                                url=self.url(image) if image.exists() else None))
        stems = [dict(id=name, url=self.url(path) if path.is_relative_to(self.folder) else None)
                 for name, path in stem_sources(self.folder, self.config['audio']).items()]
        with LOCK:
            busy = bool(self.state['action'] or self.state['queued_actions']) or self.state['status'] in ('queued', 'running', 'review')
            status = self.state['status']
        return dict(duration=duration, lines=data, art=art, custom_art=any(a['start'] != a['default_start'] for a in art),
                    stems=stems, editable=not busy, status=status, has_video=(self.folder/'video.mp4').exists(),
                    timeline_dirty=bool(self.state.get('timeline_dirty')))

    def save_timeline(self, args):
        from timeline import ART_TIMES, apply_edits, checked_art_times, rewrite_lyrics, save_art_times
        if self.state['action'] or self.state['queued_actions'] or self.state['status'] in ('queued', 'running', 'review'):
            raise ValueError('The timeline can be edited once the video is finished or stopped')
        timings = self.folder/'video.timings.json'
        data = json.loads(timings.read_text(encoding='utf-8'))
        duration = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', self.config['audio']], text=True))
        edited = apply_edits(data, args.get('lines'), duration)
        starts = args.get('art_starts')
        if starts is not None:
            count = len(json.loads(self.manifest().read_text(encoding='utf-8'))['prompts'])
            starts = checked_art_times(starts, count, duration)
        temporary = timings.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(edited, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(timings)
        save_art_times(self.folder, starts)
        texts = [line['text'] for line in edited]
        for name in ('lyrics.txt', 'video.lyrics.txt'):
            path = self.folder/name
            if path.is_file():
                path.write_text(rewrite_lyrics(path.read_text(encoding='utf-8-sig'), texts), encoding='utf-8')
        if (self.folder/'video.mp4').exists():
            self.state['timeline_dirty'] = True
        self.log('Timeline saved: word timing, lyrics and illustration times updated.')
        self.save()

    def manifest(self):
        from active_artwork import select_manifest
        return select_manifest(self.folder,self.config,self.state)

    def images(self):
        try:
            manifest = self.manifest()
            job = json.loads(manifest.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            return []
        result = []
        for i, prompt in enumerate(job['prompts']):
            current, raw = manifest.parent/f'{i:03d}.png', manifest.parent/f'{i:03d}.raw.png'
            variants = [p for p in (current, raw) if p.exists()]
            variants += sorted((self.folder/'candidates'/f'{i:03d}').glob('*/*.png'))
            variants += sorted((self.folder/'versions'/f'{i:03d}').glob('*.png'))
            entries = []
            seen = set()
            for path in variants:
                if '.tmp.' in path.name or '.rejected-' in path.name or (path.name == '000.raw.png' and path.parent != manifest.parent):
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
                from artwork_metadata import variant_metadata
                metadata=variant_metadata(path,job,i)
                entries.append(dict(prompt=metadata.get('prompt',prompt),subject=metadata.get('subject',''),path=path.relative_to(self.folder).as_posix(), url=self.url(path),
                    current=path == current, raw=path == raw, fresh=path.is_relative_to(self.folder/'candidates') and stat.st_mtime>=self.state['started'], review=review))
            queued=next((q for q in self.state.get('queued_actions',[]) if q.get('index')==i and q.get('action','regenerate') in ('regenerate','reprompt')),None)
            pending=('Prompt queued' if queued.get('action')=='reprompt' else 'Image queued') if queued else ''
            if i in self.state.get('active_images',[]) :
                pending='Preparing prompt' if self.state.get('action_stage')=='subjects' else 'Generating replacement'
            result.append(dict(index=i, pending=pending, subject=job.get('visual_descriptions', job['prompts'])[i],
                lyrics=job['groups'][i], prompt=prompt, variants=entries))
        return result


def checked_file(job, value):
    path = (job.folder/value).resolve()
    if not path.is_relative_to(job.folder.resolve()) or not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError('Select an image belonging to this job')
    return path


def stop_job(job):
    with LOCK:
        job.cancelled = True
        from generation_queue import queue_path
        queue_path(job.folder).unlink(missing_ok=True)
        for process in (job.action_process, job.process):
            if process and process.poll() is None:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
                else:
                    os.killpg(process.pid, signal.SIGTERM)
        job.state.update(status='cancelled', action=None, queued_actions=[], message='Cancelled; saved files retained', finished=time.time())
        job.save()


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


def start_job(fields, files):
    with LOCK:
        if any(j.state['status'] in ('queued', 'running', 'review') or j.state['action'] for j in JOBS.values()):
            raise ValueError('Finish or cancel the active job before starting another GPU job')
        project_id = fields.get('project_id', '').strip()
        start_step = fields.get('start_step', 'beginning').strip()
        ai_model = fields.get('ai_model', 'auto').strip()
        is_restart = bool(start_step != 'beginning' and project_id and (ROOT / project_id).is_dir())
        if ai_model not in ('','auto') or fields.get('auto_verify')=='on':
            from gpu_models import validate_selected_models
            ai_model=validate_selected_models(ai_model,fields.get('vision_model',''),fields.get('auto_verify')=='on')

        if not files.get('audio'):
            if is_restart:
                existing_audio = list((ROOT / project_id).glob('audio.*'))
                if existing_audio:
                    filename = existing_audio[0].name
                    audio_bytes = existing_audio[0].read_bytes()
                else:
                    raise ValueError('Choose an audio file')
            else:
                raise ValueError('Choose an audio file')
        else:
            filename, audio_bytes = files['audio'][0]
        suffix = Path(filename).suffix.lower()
        if suffix not in AUDIO_SUFFIXES or not audio_bytes:
            raise ValueError('Unsupported or empty audio file')
        lyrics = fields.get('lyrics', '').strip()
        width, height = {'720p': (1280, 720), '1080p': (1920, 1080), 'portrait': (720, 1280)}[fields.get('resolution', '720p')]
        asr_model=fields.get('asr_model',DEFAULT_ASR)
        alignment_model=fields.get('alignment_model','auto')
        validate_speech(asr_model,fields.get('language','auto'),alignment_model,has_lyrics=bool(lyrics))
        image_model = fields.get('image_model', MODEL)
        spec = next((m for m in MODELS if m['id'] == image_model), None)
        if spec is None:
            raise ValueError('Choose a supported image model')
        steps, lines = int(fields.get('steps') or spec['steps']), int(fields.get('lines', 2))
        if not 1 <= steps <= 150 or not 1 <= lines <= 50:
            raise ValueError('Steps must be 1–150; lines per image must be 1–50')
        if is_restart:
            folder = ROOT / project_id
        else:
            folder = ROOT/(time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(3))
            folder.mkdir(parents=True, exist_ok=True)
        audio = folder/('audio'+suffix)
        if not audio.exists() or audio_bytes:
            audio.write_bytes(audio_bytes)
        (folder/'lyrics.txt').write_text(lyrics, encoding='utf-8')
        refs = [store_image(folder/'references', name, content) for name, content in files.get('references', [])]
        image_seed=secrets.randbelow(2**31)
        if is_restart and start_step in ('images','review','render'):
            try:image_seed=json.loads((folder/'config.json').read_text(encoding='utf-8')).get('image_seed',image_seed)
            except (OSError,ValueError):pass
        config = dict(name=Path(filename).stem, audio=str(audio), width=width, height=height, fps=30,
            image_cache=str(Path(fields.get('cache', '').strip() or str(default_model_cache())).expanduser().resolve()),
            style_prompt=fields.get('reference_prompt', '').strip() or STYLE_PROMPT,
            theme=fields.get('style', '').strip() or 'Bright, uplifting mood; flowing fabric and long flowing hair; graceful movement and luminous color.',
            artwork_mode=fields.get('artwork_mode','cutout'), image_seed=image_seed,
            cinematic=fields.get('cinematic') == 'on', encoder=fields.get('encoder', 'h264_nvenc'),
            illustration_lines=lines, steps=steps, image_model=image_model, asr_model=asr_model, alignment_model=alignment_model,
            particle_intensity=float(fields.get('particle_intensity', 1.)),
            particle_speed=float(fields.get('particle_speed', 1.)),
            text_animation=fields.get('text_animation','directed'), entrance_effect=fields.get('entrance_effect', 'legacy'), exit_effect=fields.get('exit_effect', 'legacy'),
            type_effect=fields.get('type_effect','mixed'), language=fields.get('language','').strip(),
            ai_model=ai_model, start_step=start_step, project_id=folder.name,
            vision_model=fields.get('vision_model','').strip(),auto_verify=fields.get('auto_verify')=='on',
            auto_accept=fields.get('auto_accept')=='on', auto_repair=fields.get('auto_repair','on')=='on',review_threshold=int(fields.get('review_threshold',DEFAULT_THRESHOLD)))
        config.update(typography_options(fields))
        if config['artwork_mode'] not in ('cutout','fullscreen','verse'):
            raise ValueError('Invalid artwork mode')
        if not 0 <= config['review_threshold'] <= 100:
            raise ValueError('Review threshold must be between 0 and 100 percent')
        if not 0 <= config['particle_intensity'] <= 2:
            raise ValueError('Particle density must be between 0 and 2')
        if config['text_animation'] not in TEXT_ANIMATIONS:
            raise ValueError('Invalid word animation')
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
        (folder/'config.json').write_text(json.dumps(config, indent=2), encoding='utf-8')

        if is_restart:
            if start_step == 'timing':
                for f in [folder/'video.timings.json', folder/'video.theme.json', folder/'video.art-times.json']:
                    if f.exists(): f.unlink()
            elif start_step == 'prompts':
                for f in [folder/'video.theme.json']:
                    if f.exists(): f.unlink()
            elif start_step == 'images':
                pass
            elif start_step == 'review':
                pass
            elif start_step == 'render':
                pass

        command = [sys.executable, '-u', str(HERE/'kinetic_lyrics.py'), str(audio)]
        if lyrics:
            command.append(str(folder/'lyrics.txt'))
        command += [
            '--theme', config['theme'], '--style-prompt', config['style_prompt'], '--image-cache', config['image_cache'],
            '--artwork-mode', config['artwork_mode'], '--image-seed', str(config['image_seed']),
            '--image-model', config['image_model'], '--image-steps', str(steps), '--illustration-lines', str(lines),
            '--width', str(width), '--height', str(height), '--encoder', config['encoder'], '--preserve-art-slots',
            '--asr-model',config['asr_model'], '--alignment-model',config['alignment_model'],
            '--type-effect',config['type_effect'], '--particle-intensity', str(config['particle_intensity']), '--particle-speed', str(config.get('particle_speed', 1.)),
            '-o', str(folder/'video.mp4')]
        command += ['--text-animation', config['text_animation'], '--text-pool',json.dumps(config['text_pool']),
                    '--font-family',config['font_family'],'--font-style',config['font_style'],'--font-scale',str(config['font_scale']),'--lettering-styles',json.dumps(config['lettering_styles']),'--reading-flow',config['reading_flow'],'--kinetic',json.dumps(config['kinetic']),'--effect-speeds',json.dumps(config['effect_speeds'])]
        if not config['auto_accept']:
            command.append('--review-artwork')
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
                        from timeline import rewrite_lyrics
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
            from generation_queue import queue_path
            pending_path=queue_path(folder)
            job.state['queued_actions'] = json.loads(pending_path.read_text(encoding='utf-8')) if pending_path.exists() else []
        else:
            job = Job(folder, config)
            JOBS[folder.name] = job
        job.save()
        threading.Thread(target=job.run, args=(command,), daemon=True).start()
        return job


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
            if url.path in ('/studio.css', '/studio-profiles.js', '/studio-models.js', '/studio-particles.js', '/studio-timeline.js', '/studio-timeline.css'):
                path = UI_ROOT/url.path.lstrip('/')
                return self.respond(path.read_bytes(), content_type='text/css' if path.suffix=='.css' else 'text/javascript')
            if url.path == '/api/profile-audio':
                from profile_audio import profile_audio_path
                value=parse_qs(url.query).get('path',[''])[0]
                try:
                    path=profile_audio_path(PROJECT_ROOT/'profiles'/'audio',value,AUDIO_SUFFIXES)
                except FileNotFoundError as exc:
                    return self.respond(dict(error=str(exc)),404)
                return self.respond(path.read_bytes(),content_type=mimetypes.guess_type(str(path))[0] or 'application/octet-stream')
            if url.path == '/api/particle-preview':
                from particle_preview import render_preview
                query = parse_qs(url.query)
                phase = query.get('phase', ['exit'])[0]
                effect = query.get('effect', [''])[0]
                if phase == 'text':
                    from particle_preview import render_text_preview
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
            if url.path == '/api/config':
                from gpu_models import PRESETS, PROMPT_MODELS, VISION_MODELS
                return self.respond(dict(token=TOKEN, auto_accept_supported=True, particle_materials_version=13, ai_typography_supported=True, typography_controls_supported=True, word_animations_supported=True, video_history_supported=True, video_history_version=2, live_artwork_version=2, replacement_priority_supported=True, particle_effects=catalog_choices(), prompt_regeneration=True, generation_queue_version=2, prompt_audit_version=1, style_prompt=STYLE_PROMPT, model=MODEL, image_models=MODELS, model_presets=PRESETS, prompt_choices=PROMPT_MODELS, vision_choices=VISION_MODELS, asr_models=ASR_MODELS, vocal_languages=LANGUAGES, default_asr=DEFAULT_ASR,
                    jobs=[dict(id=j.folder.name, name=j.config['name']) for j in reversed(list(JOBS.values()))]))
            if url.path == '/api/gpu':
                from gpu_telemetry import gpu_usage
                return self.respond(gpu_usage())
            if url.path == '/api/downloads':
                from model_downloads import download_status
                return self.respond(download_status())
            if url.path in ('/api/models','/api/models/best'):
                from gpu_models import model_choices
                from ollama_service import local_json
                return self.respond(model_choices(local_json,review=parse_qs(url.query).get('review',['1'])[0]!='0'))
            if url.path.startswith('/api/projects/') and url.path.endswith('/status'):
                project_id = url.path.split('/')[3]
                folder = ROOT / project_id
                if not folder.is_dir():
                    return self.respond(dict(exists=False), 404)
                manifests = (list((folder / 'video.artwork').glob('*/illustrations.json')) +
                             list((folder / 'video.artwork').glob('illustrations.json')) +
                             list(folder.glob('illustrations.json')))
                from active_artwork import select_manifest
                try:manifest=select_manifest(folder)
                except ValueError:
                    manifest=next((p for p in manifests if p.parent in (folder,folder/'video.artwork')),None)
                images, reviews = [], []
                if manifest and manifest.parent.is_dir():
                    images = [p.name for p in manifest.parent.glob('[0-9][0-9][0-9].png') if not p.name.endswith('.raw.png')]
                    reviews = [p.name for p in manifest.parent.glob('*.review.json')]
                if not images and manifest and manifest.parent in (folder,folder/'video.artwork'):
                    images = [p.name for p in (folder / 'video.artwork').glob('*/*.png') if not p.name.endswith('.raw.png')]
                if not reviews and manifest and manifest.parent in (folder,folder/'video.artwork'):
                    reviews = [p.name for p in (folder / 'video.artwork').glob('*/*.review.json')]
                has_timings = (folder / 'video.timings.json').exists()
                has_prompts = bool(manifest and manifest.exists())
                has_video = (folder / 'video.mp4').exists()
                current_step = 5 if has_video else 4 if reviews else 3 if images else 2 if has_prompts else 1 if has_timings else 0
                return self.respond(dict(
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
                return self.respond(JOBS[url.path.split('/')[3]].timeline())
            if url.path.startswith('/api/jobs/') and '/waveform/' in url.path:
                from timeline import stem_sources, waveform
                _, _, _, job_id, _, stem = url.path.split('/')
                job = JOBS[job_id]
                sources = stem_sources(job.folder, job.config['audio'])
                if stem not in sources:
                    return self.respond(dict(error='This stem is not available'), 404)
                return self.respond(waveform(sources[stem], job.folder/'waveforms'/f'{stem}.json'))
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
                from model_downloads import request_downloads,cancel_downloads
                args=json.loads(body)
                return self.respond(cancel_downloads(args.get('ids',[])) if route.endswith('/cancel') else request_downloads(args.get('models',[])))
            if route == '/api/profile-audio':
                from profile_audio import store_profile_audio
                fields,files=parse_form(body,self.headers['Content-Type'])
                if len(files.get('audio',[]))!=1:
                    raise ValueError('Choose one audio file')
                name,content=files['audio'][0]
                path=store_profile_audio(PROJECT_ROOT/'profiles'/'audio',name,content,AUDIO_SUFFIXES)
                return self.respond(dict(path=str(path)),201)
            if route == '/api/jobs':
                fields, files = parse_form(body, self.headers['Content-Type'])
                return self.respond(dict(id=start_job(fields, files).folder.name), 201)
            _, _, _, job_id, operation = route.split('/')
            job = JOBS[job_id]
            if operation == 'cancel':
                stop_job(job)
                return self.respond(dict(ok=True))
            if self.headers.get('Content-Type', '').startswith('multipart/'):
                args, files = parse_form(body, self.headers['Content-Type'])
            else:
                args, files = json.loads(body), {}
            if operation in ('regenerate','reprompt') and (not isinstance(args.get('prompt',''),str) or len(args.get('prompt',''))>32768):
                raise ValueError('The generation prompt must be text no longer than 32,768 characters')
            with LOCK:
                if operation == 'timeline':
                    job.save_timeline(args)
                    return self.respond(dict(ok=True))
                if operation in ('regenerate','reprompt') and (job.state['status'] == 'running' or job.state['action']):
                    index = int(args.get('index', -1))
                    count = len(json.loads(job.manifest().read_text(encoding='utf-8'))['prompts'])
                    if not 0 <= index < count:
                        raise ValueError('Invalid illustration index')
                    job.queue_generation(index,operation,str(args.get('prompt','')),str(args.get('model') or job.config.get('ai_model','auto')))
                    job.log(f'Illustration {index+1} regeneration queued for the next GPU review pause.')
                    job.save()
                    return self.respond(dict(ok=True, queued=True))
                if job.state['action'] and not (operation in ('select','replace') and job.state['action'] in ('verify','regenerate')):
                    raise ValueError('Wait for the current image operation to finish')
                live_selection = (operation in ('select', 'replace') and job.state['status'] == 'running'
                                  and job.state['stage'] in ('illustrations','cutouts','verification','repair','repair-complete','direction','render'))
                if job.state['status'] not in ('review', 'complete') and not live_selection:
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
                    from generation_queue import replacement_review_path
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
                    if job.state['status'] != 'complete' or job.state['queued_actions']:
                        raise ValueError('Wait for the current video and queued operations to finish')
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
                    typography = typography_options(dict(job.config,**args))
                    job.config.update(**typography,text_animation=text_animation, entrance_pool=entrance_pool, exit_pool=exit_pool, type_effect=effect, particle_intensity=density, particle_speed=speed,
                                      entrance_effect=entrance, exit_effect=exit_effect)
                    (job.folder/'config.json').write_text(json.dumps(job.config, indent=2), encoding='utf-8')
                    command = [sys.executable, '-u', str(HERE/'studio_worker.py'), 'rerender', str(job.folder)]
                    job.state.update(action='rerender', action_percent=0, message='Rebuilding video with selected letter effects')
                    threading.Thread(target=job.run, args=(command, 'rerender'), daemon=True).start()
                    return self.respond(dict(ok=True))
                if operation == 'rebuild':
                    from video_versions import verified_changes
                    changes, verified = verified_changes(job.folder, job.state['dirty'])
                    if verified:job.state['dirty'] = changes
                    if job.state['status'] != 'complete':
                        raise ValueError('Rebuild is available after the first video completes')
                    if job.state.get('timeline_dirty'):
                        raise ValueError('The timeline changed, so the whole video needs rebuilding. Use Rebuild video in the timeline editor.')
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
                if operation in ('select', 'replace'):
                    if operation == 'replace':
                        name, content = files['replacement'][0]
                        selected = store_image(job.folder/'candidates'/f'{index:03d}'/str(time.time_ns()), name, content)
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
                            from artwork_metadata import variant_metadata
                            archived=versions/f'{time.time_ns()}.png';shutil.copy2(target,archived)
                            archive_job=json.loads(manifest.read_text(encoding='utf-8'))
                            archived.with_suffix('.artwork.json').write_text(json.dumps(variant_metadata(target,archive_job,index)),encoding='utf-8')
                        from filelock import FileLock
                        with FileLock(str(target)+'.write.lock',timeout=30):
                            temporary=target.with_suffix('.selected.tmp.png')
                            shutil.copy2(selected,temporary)
                            temporary.replace(target)
                            target.with_suffix('.selection.json').write_text(json.dumps(dict(selected=str(selected),time=time.time())),encoding='utf-8')
                            candidate_review=selected.with_suffix('.review.json')
                            try:chosen_report=json.loads(candidate_review.read_text(encoding='utf-8'))
                            except (OSError,ValueError):chosen_report={}
                            if chosen_report.get('image_sha256')==hashlib.sha256(target.read_bytes()).hexdigest():
                                chosen_report['image']=str(target)
                                target.with_suffix('.review.json').write_text(json.dumps(chosen_report,indent=2),encoding='utf-8')
                            else:target.with_suffix('.review.json').unlink(missing_ok=True)
                            from artwork_metadata import variant_metadata,select_metadata
                            selection_job=json.loads(manifest.read_text(encoding='utf-8'))
                            select_metadata(manifest,index,variant_metadata(selected,selection_job,index))
                        if (job.folder/'video.mp4').exists() and index not in job.state['dirty']:
                            job.state['dirty'].append(index)
                    job.log(f'Illustration {index+1} selected. '+('Rebuild this section to update the video.' if (job.folder/'video.mp4').exists() else 'Selection will be used in the render.'))
                    job.save()
                    return self.respond(dict(ok=True))
                if operation in ('regenerate','reprompt'):
                    job.queue_generation(index,operation,str(args.get('prompt','')),str(args.get('model') or job.config.get('ai_model','auto')))
                    job.start_next();job.save()
                    return self.respond(dict(ok=True,queued=True))
                if operation not in ('regenerate', 'verify', 'patch'):
                    raise ValueError('Unknown operation')
                if operation == 'patch' and job.state['status'] != 'complete':
                    raise ValueError('Section rebuild is available after the video completes')
                command = [sys.executable, '-u', str(HERE/'studio_worker.py'), operation, str(job.folder), '--index', str(index)]
                if operation == 'verify':
                    if not args.get('model'):
                        raise ValueError('Choose an installed Ollama vision model')
                    selected = checked_file(job, args['path'])
                    command += ['--model', args['model'], '--candidate', str(selected)]
                if operation == 'regenerate':
                    command += ['--prompt', str(args.get('prompt', ''))[:5000]]
                job.state.update(action=operation, action_percent=0, message=f'Starting {operation}')
                threading.Thread(target=job.run, args=(command, operation), daemon=True).start()
                return self.respond(dict(ok=True))
        except (ValueError, KeyError, OSError, IndexError) as exc:
            self.respond(dict(error=str(exc)), 400)


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
                from generation_queue import queue_path
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
