"""Runs a job's pipeline and worker actions as child processes. Progress events update the job
state, a failed run resumes from saved work, and a crashed image worker is retried.
Job (studio/server.py) inherits this."""

import codecs
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time

from core.paths import PROJECT_ROOT
from core.process import module_env
from core.progress import PREFIX
from studio.lock import LOCK

# Each stage's share of the progress bar, in percent. Prompting is split into its real steps, which
# together take longer than image generation.
STAGES = {'alignment': (0, 8), 'song': (8, 10), 'meanings': (10, 14), 'story': (14, 18), 'scenes': (18, 30),
          'fit': (30, 34), 'subjects': (8, 34), 'model': (34, 36),
          'references': (36, 37), 'reference-check': (37, 38), 'illustrations': (38, 72),
          'illustration-check': (72, 74), 'verification': (72, 74), 'repair': (72, 74),
          'cutouts': (74, 80), 'review': (80, 80), 'video': (80, 82),
          'direction': (82, 83), 'pictures': (83, 85), 'render': (85, 99), 'complete': (100, 100)}
AUTO_RESUMES = 2  # resumes after a failed run, each AUTO_RESUME_DELAY seconds later
AUTO_RESUME_DELAY = 20
CRASH_RETRIES = 2  # retries after an image worker crash; each wait is CRASH_RETRY_DELAY longer
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


class ProcessWork:
    def run(self, command, action=None):
        with LOCK:
            self.runs += 1
            if not action:self.command = command
        try:self._run(command, action)
        finally:
            with LOCK:self.runs -= 1
            if '--batch' in command:  # the batch file only hands the queued items to this one worker
                Path(command[command.index('--batch')+1]).unlink(missing_ok=True)

    def _run(self, command, action=None):
        began = time.time()
        try:
            stop_file = self.folder/f'.stop-{time.time_ns()}'  # this run's own: a new run cannot clear an older run's request
            env = module_env(dict(os.environ, KINETIC_STOP_FILE=str(stop_file), PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8', KINETIC_PROGRESS='1',
                                  OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1'))
            kwargs = dict(creationflags=subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == 'nt' else dict(start_new_session=True)
            with LOCK:
                if self.cancelled:
                    return
                process = subprocess.Popen(command, cwd=PROJECT_ROOT.parent, env=env, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, **kwargs)
                process.stop_file = stop_file
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
            stop_file.unlink(missing_ok=True)
            with LOCK:
                if action and not code and not self.cancelled:
                    from studio.eta import measure_action
                    # an upscale would read as slow animation; a looped cinemagraph or a still as fast
                    if (not self.state.get('animating_upscale') and self.config.get('video_upscale') != 'auto'
                            and self.config.get('picture_kinds', 'storyboard') == 'storyboard'):
                        measure_action(self, action, time.time()-began, list(self.state.get('animating') or []))
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
                    elif action == 'clip-effects' and not code and (self.folder/'video.mp4').exists():
                        self.record_scene_windows()
                        for index in self.state.get('effecting', []):
                            if index not in self.state['dirty']:
                                self.state['dirty'].append(index)
                        self.queue_final_cut(self.state.get('effecting', []))
                    elif action == 'scene-scan' and not code:
                        self.place_scene_lyrics()
                    elif action == 'animate' and not code and (self.folder/'video.mp4').exists():
                        self.queue_effects_after_animation()
                        for index in self.state.get('animating', []):
                            if index not in self.state['dirty']:
                                self.state['dirty'].append(index)
                        # this batch's clips, and any clip newer than the video (made when nothing queued its rebuild)
                        self.queue_final_cut(list(self.state.get('animating', []))+self.clips_newer_than_video())
                    finished = 'Upscale' if self.only_upscaled(action) else action.capitalize()
                    self.state.update(action=None, active_images=[], animating=[], animating_segments={}, animating_upscale=[], redo_pending={}, effecting=[], action_stage=None,
                                      action_percent=100 if not code else 0)
                    if not code and action!='repair':
                        self.state['message'] = f'{finished} complete'
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
                if not code and action != 'animate':  # never re-queue itself: a clip it could not make would loop
                    self.queue_missing_clips()
                if not code and not self.cancelled:
                    from studio.pipeline_history import capture
                    if action in ('regenerate', 'reprompt', 'repair', 'reference'):
                        capture(self.folder, 'images', force=True, attempt=began)
                    elif action in ('animate', 'clip-effects'):
                        capture(self.folder, 'video', force=True, attempt=began)
                        if action == 'clip-effects':
                            capture(self.folder, 'scene-scan', force=True, attempt=began)
                    elif action == 'scene-scan':
                        capture(self.folder, 'scene-scan', force=True, attempt=began)
                    if not action or action in ('patch', 'rerender'):
                        if action:
                            # A successful rebuild used the current accepted pictures
                            # and typography, even when their preceding edit was manual.
                            capture(self.folder, 'review', attempt=began)
                            capture(self.folder, 'render', force=action == 'rerender', attempt=began)
                        capture(self.folder, 'final', force=True, attempt=began)
                self.save()
                if not code and action == 'reference' and not self.cancelled:
                    self.state.pop('reference_batch', None)
                    resume = self.state.pop('reference_resume_command', None)
                    self.save()
                    if resume:
                        self.state.update(status='running', action=None, message='References updated; resuming the pipeline')
                        self.save()
                        threading.Thread(target=self.run, args=(resume,), daemon=True).start()
                        return
                self.start_next()
        except Exception as exc:
            with LOCK:
                self.log(str(exc), 'error')
                self.state.update(action=None, message=str(exc))
                if not action:
                    self.state['status'] = 'failed'
                    self.state['finished'] = time.time()
                self.save()

    def only_upscaled(self, action):
        """This animate batch upscaled finished clips and made none."""
        batch = self.state.get('animating') or []
        return action == 'animate' and bool(batch) and set(batch) <= set(self.state.get('animating_upscale') or [])

    def event(self, event, action=False):
        with LOCK:
            if self.cancelled:  # a cancelled run finishing its step: its progress is no longer news
                return
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
                           else {'model':(0,10),'references':(10,12),'illustrations':(12,80),'cutouts':(80,100),'candidate':(100,100)}
                           if self.state['action'] in ('regenerate','reprompt') else {})
                lo,hi=weights.get(event['stage'],(0,100))
                self.state['action_percent'] = max(self.state['action_percent'],round(lo+(hi-lo)*fraction,1))
            else:
                stage = event['stage']
                now = time.time()
                if stage != self.state.get('stage'):  # a step ended: its duration is measured (see studio.eta)
                    from studio.eta import measure_stage
                    measure_stage(self, self.state.get('stage'), self.state.get('stage_started'), now)
                    self.state['stage_started'] = now
                if stage == 'illustrations' and ' saved' in str(event.get('message', '')):
                    from studio.eta import measure_image
                    last = self.state.get('image_saved_at')
                    if last:
                        measure_image(self, now-last)
                    self.state['image_saved_at'] = now
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
            self.state['detail_at'] = time.time()  # the video worker's own time left counts down from here
            if not action and event['stage'] == 'review':
                if self.config.get('auto_verify') and self.config.get('vision_model') and not self.state.get('auto_review_queued'):
                    self.queue_reviews(self.config['vision_model'])
                    self.state['auto_review_queued']=True
                self.start_next()

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
        timer = threading.Timer(delay+.5, self.start_next)
        timer.daemon = True  # never keeps a stopping server alive
        timer.start()
        self.log(f'The image model crashed while working (exit {code}), usually because system memory ran out. {memory} '
                 f'Retrying {len(retry)} image request(s) in {delay}s (attempt {attempt}/{CRASH_RETRIES}).', 'warning')
        self.state['message'] = f'Image model crashed; retrying in {delay}s'
        return True

    def queue_final_cut(self, indices):
        """Final cut: rebuild the sections whose clips just changed (new AI clips, in-scene lyrics, clip effects), so
        the finished video gets them without a Rebuild click. Queued after the effects a new clip has re-applied, so
        each section is rebuilt once with everything in it."""
        if self.state.get('status') != 'complete' or not (self.folder/'video.mp4').exists():
            return
        if any(a.get('action') == 'rerender' for a in self.state['queued_actions']):
            return  # a full re-render (after a timing edit) takes every clip in already
        queued = {a.get('index') for a in self.state['queued_actions'] if a.get('action') == 'patch'}
        self.state['queued_actions'].extend(dict(action='patch', index=i) for i in sorted(set(indices)-queued))

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
