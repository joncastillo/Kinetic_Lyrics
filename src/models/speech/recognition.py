"""Speech entry points: transcribe lyrics, or align supplied lyrics to the vocals."""
from __future__ import annotations
from core.process import run
from models.speech.whisper import release_whisper_memory, whisper_model
from core.text import normalized


def transcribe(audio, args):
    """Recover lyric lines and word timing together when no text is supplied."""
    if getattr(args,'asr_model','legacy') != 'legacy':
        from models.speech.catalog import transcribe_selected
        return transcribe_selected(audio,args)
    print(f'Transcribing lyrics with Whisper {args.model} ({args.device})...', flush=True)
    model = whisper_model(args)
    try:
        result = model.transcribe(str(audio), language=args.language,
            task='transcribe', word_timestamps=True, regroup=True)
    finally:
        model.cpu()
        del model
        release_whisper_memory()
    data = []
    if result is not None:
        for segment in result.to_dict().get('segments', []):
            words = [dict(text=w['word'].strip(), start=w['start'], end=w['end'])
                     for w in segment.get('words', []) if w.get('word', '').strip()]
            if words:
                data.append(dict(text=' '.join(w['text'] for w in words), words=words))
            elif segment.get('text', '').strip():
                raise ValueError('Whisper returned text without word timestamps; supply reviewed lyrics/timings.')
    if not data:
        raise ValueError('Whisper found no lyrics. Supply a lyrics file or try --alignment-audio with isolated vocals.')
    print('Whisper lyrics are an estimate: review the saved .lyrics.txt and .timings.json.', flush=True)
    return data

def align(audio, lines, args):
    from models.speech.catalog import ALIGN_LANGUAGES, qwen_alignment
    import copy
    options=copy.copy(args)
    choice=getattr(args,'alignment_model','legacy')
    duration=float(run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(audio)])) if choice=='auto' else 0
    use_qwen=choice=='qwen3-aligner' or (choice=='auto' and args.language in ALIGN_LANGUAGES and duration<=300)
    if use_qwen:
        words=qwen_alignment(audio,lines,args)
    else:
        if choice in ('auto','whisper-large-v3'):options.model='large-v3'
        elif choice=='whisper-turbo':options.model='turbo'
        print(f'Aligning supplied lyrics with Whisper {options.model} ({args.device})...',flush=True)
        model=whisper_model(options)
        try:
            language=args.language
            if not language:
                import whisper
                waveform=whisper.load_audio(str(audio))
                mel=whisper.log_mel_spectrogram(whisper.pad_or_trim(waveform),n_mels=model.dims.n_mels).to(model.device)
                _,probabilities=model.detect_language(mel)
                language=max(probabilities,key=probabilities.get)
                print('Detected alignment language: '+language,flush=True)
            result=model.align(str(audio),"\n".join(lines),language=language,original_split=True,regroup=False)
        finally:
            model.cpu();del model;release_whisper_memory()
        if result is None:raise ValueError('No vocals could be aligned. Try a vocal stem.')
        words=[w for segment in result.to_dict()['segments'] for w in segment.get('words',[])]
    target = ''.join(normalized(line) for line in lines)
    actual = ''.join(normalized(w['word']) for w in words)
    if target != actual:
        raise ValueError("Aligner did not retain all lyric text. Check the lyrics or supply --timings.")
    spans, offset = [], 0
    for word in words:
        length = len(normalized(word['word']))
        if length:
            spans.append((offset, offset + length, float(word['start']), float(word['end'])))
        offset += length
    offset, output = 0, []
    for line in lines:
        timed = []
        for word in line.split():
            length = len(normalized(word))
            matches = [s for s in spans if s[0] < offset + length and s[1] > offset]
            if not matches:
                if not length and timed:
                    timed[-1]['text'] += ' ' + word
                    continue
                raise ValueError(f"Cannot align token {word!r}; remove standalone punctuation.")
            timed.append(dict(text=word, start=matches[0][2], end=matches[-1][3]))
            offset += length
        output.append(dict(text=line, words=timed))
    return output
