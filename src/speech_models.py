"""Speech model catalog and isolated inference entry points."""
from project_paths import PROJECT_ROOT, default_model_cache
import copy,json,os,subprocess,sys,tempfile,site
from pathlib import Path
from filelock import FileLock
HERE=Path(__file__).resolve().parent
LANGUAGES=json.loads((HERE/'whisper_languages.json').read_text(encoding='utf-8'))
QWEN_LANGUAGES='zh en yue ar de fr es pt id it ko ru th vi ja tr hi ms nl sv da fi pl cs tl fa el hu mk ro'.split()
PARAKEET_LANGUAGES='bg hr cs da nl en et fi fr de el hu it lv lt mt pl pt ro sk sl es sv ru uk'.split()
ALIGN_LANGUAGES='zh en yue fr de it ja ko pt ru es'.split()
ASR_MODELS=[
 dict(id='qwen3-asr-1.7b',name='Qwen3 ASR 1.7B',repo='Qwen/Qwen3-ASR-1.7B-hf',engine='qwen',languages=QWEN_LANGUAGES,description='Multilingual transcription, including Filipino. Separate word alignment.'),
 dict(id='qwen3-asr-0.6b',name='Qwen3 ASR 0.6B',repo='Qwen/Qwen3-ASR-0.6B-hf',engine='qwen',languages=QWEN_LANGUAGES,description='Smaller, faster Qwen model. Separate word alignment.'),
 dict(id='parakeet-v3',name='NVIDIA Parakeet TDT v3',repo='nvidia/parakeet-tdt-0.6b-v3',engine='parakeet',languages=PARAKEET_LANGUAGES,description='25 European languages; native timestamps. Does not support Tagalog.'),
 dict(id='whisper-large-v3',name='Whisper Large v3',repo='openai/whisper-large-v3',engine='whisper',model='large-v3',languages=list(LANGUAGES),description='Broad language coverage; transcription and lyric alignment.'),
 dict(id='whisper-turbo',name='Whisper Large v3 Turbo',repo='openai/whisper-large-v3-turbo',engine='whisper',model='turbo',languages=list(LANGUAGES),description='Faster Whisper option with broad language coverage.'),
]
DEFAULT_ASR='qwen3-asr-1.7b'
ALIGNERS=('auto','qwen3-aligner','whisper-large-v3','whisper-turbo')
TRANSFORMERS_SOURCE='https://github.com/huggingface/transformers/archive/05a2d95bf36096f79a85af682ac387beb68f447b.zip'

def asr_spec(value):
    return next((m for m in ASR_MODELS if m['id']==value),None)

def validate_speech(model,language,aligner='auto',has_lyrics=False):
    spec=asr_spec(model)
    if spec is None:raise ValueError('Choose a supported audio model')
    if language not in ('auto','',None) and language not in LANGUAGES:raise ValueError('Unsupported vocal language')
    if not has_lyrics and language not in ('auto','',None) and language not in spec['languages']:
        raise ValueError(f"{spec['name']} does not support {LANGUAGES[language]}; choose another audio model")
    if aligner not in ALIGNERS:raise ValueError('Choose a supported word timing model')
    if aligner=='qwen3-aligner' and language not in ALIGN_LANGUAGES:
        raise ValueError('Qwen word alignment needs an explicit supported language; choose Auto timing for other languages')
    return spec

def ensure_runtime():
    folder=PROJECT_ROOT/'.runtime'/'asr';python=folder/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    marker=folder/'studio-ready.json'
    (PROJECT_ROOT/'.runtime').mkdir(exist_ok=True)
    with FileLock(str(PROJECT_ROOT/'.runtime'/'asr-install.lock'),timeout=900):
        if not python.exists():
            subprocess.run([sys.executable,'-m','venv','--system-site-packages',str(folder)],check=True)
        packages=folder/('Lib/site-packages' if os.name=='nt' else f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages')
        inherited='\n'.join(site.getsitepackages())+'\n'
        (packages/'studio-parent-packages.pth').write_text(inherited,encoding='utf-8')
        if marker.exists() and python.exists():return python
        check='import torch; from transformers import Qwen3ASRForConditionalGeneration,Qwen3ASRForTokenClassification,AutoModelForTDT'
        if python.exists() and subprocess.run([str(python),'-c',check],capture_output=True).returncode==0:
            marker.write_text(json.dumps({'source':TRANSFORMERS_SOURCE}),encoding='utf-8');return python
        print('Preparing isolated speech runtime; first use downloads runtime dependencies.',flush=True)
        if not python.exists():subprocess.run([sys.executable,'-m','venv','--system-site-packages',str(folder)],check=True)
        subprocess.run([str(python),'-m','pip','install','--no-deps','--ignore-installed','transformers @ '+TRANSFORMERS_SOURCE],check=True)
        subprocess.run([str(python),'-m','pip','install','tokenizers>=0.23.1,<0.24','huggingface-hub>=1.31,<3'],check=True)
        subprocess.run([str(python),'-c',check],check=True)
        marker.write_text(json.dumps({'source':TRANSFORMERS_SOURCE}),encoding='utf-8')
    return python

def speech_worker(mode,audio,args,lines=None):
    python=ensure_runtime()
    tokenizer={'ja':'nagisa>=0.3,<0.4','ko':'soynlp>=0.0.493,<0.1'}.get(args.language) if mode=='align' else None
    if tokenizer:
        module=tokenizer.split('>')[0]
        check=f'import importlib.util; raise SystemExit(0 if importlib.util.find_spec({module!r}) else 1)'
        if subprocess.run([str(python),'-c',check],capture_output=True).returncode:
            with FileLock(str(PROJECT_ROOT/'.runtime'/'asr-install.lock'),timeout=900):
                subprocess.run([str(python),'-m','pip','install','--only-binary=:all:',tokenizer],check=True)
    cache=Path(getattr(args,'image_cache',None) or str(default_model_cache())).expanduser().resolve()/'speech'
    cache.mkdir(parents=True,exist_ok=True)
    request=dict(mode=mode,audio=str(audio),model=args.asr_model,language=args.language,
                 device=args.device,cache=str(cache),lines=lines)
    with tempfile.TemporaryDirectory(prefix='speech-',dir=PROJECT_ROOT/'.runtime') as tmp:
        folder=Path(tmp);source=folder/'request.json';output=folder/'result.json'
        source.write_text(json.dumps(request),encoding='utf-8')
        subprocess.run([str(python),'-u',str(HERE/'speech_worker.py'),str(source),str(output)],check=True)
        return json.loads(output.read_text(encoding='utf-8'))

def group_words(words,max_words=9):
    lines=[];current=[]
    for word in words:
        if current and (len(current)>=max_words or word['start']-current[-1]['end']>.8):
            lines.append(dict(text=' '.join(w['text'] for w in current),words=current));current=[]
        current.append(word)
    if current:lines.append(dict(text=' '.join(w['text'] for w in current),words=current))
    return lines

def transcribe_selected(audio,args):
    from kinetic_lyrics import transcribe,align
    spec=validate_speech(args.asr_model,args.language,args.alignment_model)
    options=copy.copy(args)
    if spec['engine']=='whisper':
        options.asr_model='legacy';options.model=spec['model']
        data=transcribe(audio,options)
        if args.alignment_model!='auto':
            return align(audio,[line['text'] for line in data],options)
        return data
    result=speech_worker('transcribe',audio,args)
    if result.get('words') and args.alignment_model=='auto':return group_words(result['words'])
    text=result['text'].strip()
    if not text:raise ValueError('No lyrics recognized; try a vocal stem or supply lyrics')
    tokens=text.split();lines=[' '.join(tokens[i:i+9]) for i in range(0,len(tokens),9)]
    if not lines:lines=[text]
    if not options.language:options.language=result.get('language') or None
    return align(audio,lines,options)

def qwen_alignment(audio,lines,args):
    result=speech_worker('align',audio,args,lines)
    return [dict(word=w['text'],start=w['start'],end=w['end']) for w in result['words']]
