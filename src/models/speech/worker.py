"""One isolated speech stage per process; GPU allocations end before the next stage."""
import gc,json,sys,subprocess,re
from pathlib import Path
import numpy as np
from models.speech.catalog import asr_spec, LANGUAGES, ALIGN_LANGUAGES
from core.progress import emit

def audio_samples(path):
    raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-f','f32le','-ac','1','-ar','16000','pipe:1'])
    return np.frombuffer(raw,dtype='<f4').copy()

def audio_chunks(samples):
    start=0;size=len(samples)
    while start<size:
        end=min(size,start+25*16000)
        if end<size:
            candidates=range(max(start+20*16000,end-2*16000),end,1600)
            end=min(candidates,key=lambda n:float(np.mean(samples[n:n+800]**2)))
        yield start/16000,samples[start:end]
        start=end

def token_words(tokens,offset):
    words=[];current=None;new=True
    for token in tokens:
        for part in re.findall(r'\s+|\S+',token['token']):
            if part.isspace():new=True;continue
            if new or current is None:
                current=dict(text=part,start=offset+float(token['start']),end=offset+float(token['end']));words.append(current)
            else:
                current['text']+=part;current['end']=offset+float(token['end'])
            new=False
    return words

def run(request):
    import torch
    from transformers import AutoProcessor,Qwen3ASRForConditionalGeneration,Qwen3ASRForTokenClassification,AutoModelForTDT
    device=request['device'];dtype=torch.bfloat16 if device=='cuda' else torch.float32
    spec=asr_spec(request['model']);cache=request['cache'];samples=audio_samples(request['audio'])
    model=None;processor=None
    language=request.get('language') or None
    if language=='auto':language=None
    language_code='fil' if language=='tl' else language
    try:
        if request['mode']=='align':
            if language not in ALIGN_LANGUAGES:raise ValueError('Unsupported Qwen alignment language')
            if len(samples)>300*16000:raise ValueError('Qwen alignment supports up to five minutes; select Auto or Whisper timing for longer songs')
            repo='Qwen/Qwen3-ForcedAligner-0.6B-hf'
            emit('alignment',.2,message='Loading Qwen3 word timing model')
            processor=AutoProcessor.from_pretrained(repo,cache_dir=cache)
            model=Qwen3ASRForTokenClassification.from_pretrained(repo,cache_dir=cache,dtype=dtype).to(device).eval()
            inputs,word_lists=processor.prepare_forced_aligner_inputs(audio=samples,transcript='\n'.join(request['lines']),language=language_code)
            inputs=inputs.to(model.device,model.dtype)
            with torch.inference_mode():outputs=model(**inputs)
            stamps=processor.decode_forced_alignment(logits=outputs.logits,input_ids=inputs['input_ids'],word_lists=word_lists,timestamp_token_id=model.config.timestamp_token_id)[0]
            return dict(words=[dict(text=w['text'],start=w['start_time'],end=w['end_time']) for w in stamps])
        repo=spec['repo'];emit('alignment',.05,message=f"Loading {spec['name']}; missing weights download automatically")
        processor=AutoProcessor.from_pretrained(repo,cache_dir=cache)
        klass=Qwen3ASRForConditionalGeneration if spec['engine']=='qwen' else AutoModelForTDT
        model=klass.from_pretrained(repo,cache_dir=cache,dtype=dtype).to(device).eval()
        texts=[];words=[];detected=language
        for offset,chunk in audio_chunks(samples):
            if spec['engine']=='qwen':
                inputs=processor.apply_transcription_request(audio=chunk,language=language_code).to(model.device,model.dtype)
                with torch.inference_mode():output=model.generate(**inputs,max_new_tokens=1024,do_sample=False)
                parsed=processor.decode(output[:,inputs['input_ids'].shape[1]:],return_format='parsed')[0]
                texts.append(parsed['transcription'])
                name=(parsed.get('language') or '').lower()
                detected=detected or next((c for c,n in LANGUAGES.items() if n==name), 'tl' if name=='filipino' else None)
            else:
                inputs=processor(chunk,sampling_rate=16000,return_tensors='pt').to(model.device,model.dtype)
                with torch.inference_mode():output=model.generate(**inputs,return_dict_in_generate=True,max_new_tokens=1024)
                decoded,stamps=processor.decode(output.sequences,durations=output.durations,skip_special_tokens=True)
                texts.append(decoded[0]);words.extend(token_words(stamps[0],offset))
            emit('alignment',.1+.65*(offset*16000+len(chunk))/len(samples),message=f"{spec['name']}: transcribed through {offset+len(chunk)/16000:.0f}s")
        return dict(text=' '.join(texts),language=detected,words=words)
    finally:
        if model is not None:model.cpu()
        model=None;processor=None;gc.collect()
        if torch.cuda.is_available():torch.cuda.empty_cache()
        print('Speech stage finished; model released before the next stage.',flush=True)

if __name__=='__main__':
    request=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    try:result=run(request)
    except Exception as exc:raise SystemExit(f'Speech model failed: {exc}')
    Path(sys.argv[2]).write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
