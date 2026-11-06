"""A job's queue of image and clip work, run one batch at a time in the worker.
Job (studio/server.py) inherits this."""

import json
from pathlib import Path
import secrets
import threading
import time

from core.files import cached_digest, content_digest
from core.process import module_command
from models.image.catalog import MODELS
from models.vision.policy import rejected, DEFAULT_THRESHOLD
from studio.lock import LOCK


# The model each kind of queued work loads: work for the same model runs back to back, so it is loaded once in a row
# instead of image, video, image. Rebuilds and re-renders load none and keep their place.
FAMILY = {'regenerate': 'image', 'reprompt': 'image', 'verify': 'image', 'repair': 'image', 'reference': 'image', 'animate': 'video'}

# What runs before what, whatever the order it was queued in: a reference picture first (the images that show it
# wait for it), then image work (the pictures are settled before any clip is made from them), then the rest.
TIER = {'reference': 0, 'regenerate': 1, 'reprompt': 1, 'verify': 1, 'repair': 1}


def next_in_queue(queued, last_family=None):
    """Index of the queued item to run next: the first reference repaint, else the first image work, else (animations,
    rebuilds, re-renders) the first that uses the model the last job used, else the first."""
    for tier in (0, 1):
        for index, item in enumerate(queued):
            if TIER.get(item.get('action', 'regenerate')) == tier:
                return index
    if last_family:
        for index, item in enumerate(queued):
            if FAMILY.get(item.get('action', 'regenerate')) == last_family:
                return index
    return 0


def queue_plan(queued, running=None, last_family=None):
    """The kinds of work in the order they will run, the running one first: what the header shows left to right.
    Follows start_next: the next item by next_in_queue, with every other item of its kind joining its batch."""
    plan = [running] if running else []
    family = FAMILY.get(running) or last_family
    rest = list(queued)
    while rest:
        item = rest.pop(next_in_queue(rest, family))
        kind = item.get('action', 'regenerate')
        generation = kind in ('regenerate', 'reprompt')
        if kind != 'patch':
            rest = [q for q in rest if not (q.get('action', 'regenerate') == kind or generation and
                                            q.get('action', 'regenerate') in ('regenerate', 'reprompt'))]
        family = FAMILY.get(kind) or family
        if not plan or plan[-1] != kind:
            plan.append(kind)
    return plan


class ActionQueue:
    def queue_reviews(self, model):
        items=self.images()
        for item in items:
            if any(v['current'] for v in item['variants']):
                self.state['queued_actions'].append(dict(action='verify',index=item['index'],model=model))
        self.log(f'Queued anatomy review for {len(items)} illustrations with {model}.')

    def queue_generation(self,index,operation,prompt,model,image_model=None,style=None,steps=None,reason=None,after=None):
        from artwork.queue import update_queue
        item=dict(request_id=secrets.token_hex(12),action=operation,index=index,prompt=prompt,model=model)
        if reason:item['reason']=reason  # 'reference': painted again because a reference it shows is being repainted
        # Held back until that reference (`after`, its id) is painted: a running job claims the queue file at once,
        # and painted the images again with the old picture before the repaint had run (see release_held).
        if after:item['after']=after
        # An art style typed in the regenerate panel applies to this one image; the session style stays as it was.
        if isinstance(style,str) and ' '.join(style.split()):item['style']=' '.join(style.split())
        if image_model is not None:
            if image_model not in {spec['id'] for spec in MODELS}:
                raise ValueError('Choose a supported image model')
            item['image_model']=image_model
        if type(steps) is int and 1 <= steps <= 150:item['steps']=steps
        position=next((i for i,a in enumerate(self.state['queued_actions']) if a.get('action')=='verify'),len(self.state['queued_actions']))
        self.state['queued_actions'].insert(position,item)
        if not self.held(item):update_queue(self.folder,append=item)
        self.leave_animation(index)

    def leave_animation(self,index):
        """A picture being replaced is not animated: its clip would show the old picture. It leaves the animation
        queue (and stops in the running batch at its next part) and waits in the image queue instead."""
        kept=[]
        for queued in self.state['queued_actions']:
            if queued.get('action') in ('animate','clip-effects'):
                if queued.get('indices'):
                    rest=[i for i in queued['indices'] if i!=index]
                    if rest:kept.append(dict(queued,indices=rest,index=rest[0]))
                    continue
                if queued.get('index')==index:continue
            kept.append(queued)
        self.state['queued_actions']=kept
        if self.state.get('action')=='animate' and index in (self.state.get('animating') or []):
            try:
                (self.clip_folder_for(index)/'skip').write_text('1',encoding='utf-8')  # read by the video worker
            except (OSError,ValueError):
                pass
            self.state['animating']=[i for i in self.state['animating'] if i!=index]

    def held(self,item):
        """The item waits for a reference repaint still in the queue."""
        pending = self.state['queued_actions'] + (self.state.get('reference_batch') or [] if self.state.get('action') == 'reference' else [])
        return bool(item.get('after')) and any(q.get('action')=='reference' and q.get('entity')==item['after'] for q in pending)

    def release_held(self):
        """Hand the queue file the regenerations whose reference has been painted (or taken out of the queue), so
        a running job can claim them now and a queued batch finds them. Called before any batch starts."""
        from artwork.queue import update_queue
        for item in self.state['queued_actions']:
            if item.get('after') and not self.held(item):
                item.pop('after',None)
                if item.get('action') in ('regenerate','reprompt'):update_queue(self.folder,append=item)

    def start_next(self):
        """References before image work, image work before animations; among the rest, work for the model the last
        job used goes first (see next_in_queue)."""
        with LOCK:
            self.release_held()
            if self.cancelled or self.state['action'] or self.state['status'] not in ('review','complete') or not self.state['queued_actions']:
                return
            if time.time() < self.retry_at:return  # a crashed image worker is waiting before its retry
            item=self.state['queued_actions'].pop(next_in_queue(self.state['queued_actions'],self.state.get('last_family')))
            operation=item.get('action','regenerate')
            if FAMILY.get(operation):self.state['last_family']=FAMILY[operation]
            generation=operation in ('regenerate','reprompt')
            batch=[item];remaining=[]
            for queued in self.state['queued_actions']:
                kind=queued.get('action','regenerate')
                # A section rebuild splices one index, so each queued patch runs on its own.
                if operation!='patch' and (kind==operation or generation and kind in ('regenerate','reprompt')):batch.append(queued)
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
                if operation=='verify' and len(batch)==1 and item.get('candidate'):command+=['--candidate',item['candidate']]
                if operation=='verify' and len(batch)==1 and item.get('user_prompt'):
                    command+=['--prompt='+item['user_prompt'],'--style='+item.get('style','')]
                if operation=='repair':command+=['--expected-sha',item['expected_sha']]
            elif operation=='regenerate':command+=['--prompt='+item.get('prompt','')]  # '=' keeps a leading '-' a value
            if (generation or len(batch)>1) and operation!='clip-effects':
                batch_path=self.folder/f'actions-{time.time_ns()}.json'
                batch_path.write_text(json.dumps(batch),encoding='utf-8');command+=['--batch',str(batch_path)]
            if operation=='clip-effects':
                indices=sorted({i for q in batch for i in (q.get('indices') or [q['index']])})
                batch_path=self.folder/f'actions-{time.time_ns()}.json'
                batch_path.write_text(json.dumps([dict(index=i) for i in indices]),encoding='utf-8')
                command=[*module_command('studio.worker'),'clip-effects',str(self.folder),'--index',str(indices[0]),'--batch',str(batch_path)]
                self.state['effecting']=indices
            if operation=='reference':
                batch_path=self.folder/f'actions-{time.time_ns()}.json'
                batch_path.write_text(json.dumps([dict(id=q['entity'], images=q.get('images', []), revision=q.get('revision')) for q in batch]),encoding='utf-8')
                command=[*module_command('studio.worker'),'reference',str(self.folder),'--batch',str(batch_path)]
                self.state['reference_batch'] = batch
                self.state['repainting']=[q.get('name') or q['entity'] for q in batch]  # the header names them
            if operation=='animate':
                command=[*module_command('studio.worker'),'animate',str(self.folder),'--index',str(item['index'])]
                if item.get('upscale'):command+=['--upscale',','.join(str(i) for i in item['upscale'])]
                self.state['animating']=list(item.get('indices') or [item['index']])
                self.state['animating_segments']=dict(item.get('segments') or {})
                self.state['animating_upscale']=list(item.get('upscale') or [])
            self.state.update(action=operation,action_percent=0,active_images=[i['index'] for i in batch] if generation else [],
                              action_stage='subjects' if operation=='reprompt' else 'model',message=f'{operation.capitalize()} batch starting')
            threading.Thread(target=self.run,args=(command,operation),daemon=True).start()

    def queue_repair(self, command):
        if not self.config.get('auto_repair',True):return
        index=int(command[command.index('--index')+1])
        target=self.manifest().parent/f'{index:03d}.png'
        selected=Path(command[command.index('--candidate')+1]) if '--candidate' in command else target
        if selected.resolve()!=target.resolve():return
        review_path=target.with_suffix('.review.json')
        if not review_path.exists():return
        review=json.loads(review_path.read_text(encoding='utf-8'))
        digest=content_digest(target)
        if review.get('image_sha256')!=digest or not rejected(review,self.config.get('review_threshold',DEFAULT_THRESHOLD)):return
        if any(a.get('action')=='repair' and a['index']==index for a in self.state['queued_actions']):return
        model=command[command.index('--model')+1]
        self.state['queued_actions'].append(dict(action='repair',index=index,model=model,expected_sha=digest))
        self.log(f'Illustration {index+1} scored {review["score"]}%; automatic regeneration queued.')

    def rejected_selections(self):
        failures=[]
        for item in self.images():
            for variant in item['variants']:
                review=variant.get('review')
                if not variant['current'] or not review or not rejected(review,self.config.get('review_threshold',DEFAULT_THRESHOLD)):continue
                path=self.folder/variant['path']
                if review.get('image_sha256')==cached_digest(path):failures.append(item['index'])  # runs on every poll
        return failures
