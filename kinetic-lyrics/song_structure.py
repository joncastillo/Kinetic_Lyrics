"""Preserve lyric sections and infer lyrical form before grouping illustration scenes."""
from collections import Counter
import json,re
from pathlib import Path


def normalized(text):return ' '.join(re.findall(r'\w+',text.casefold()))


def annotate_sections(data,lyrics=None):
    entries=[];label='';section=0;has_labels=False;paragraph=0;gap=False
    if lyrics and Path(lyrics).is_file():
        for raw in Path(lyrics).read_text(encoding='utf-8-sig').splitlines():
            line=raw.strip()
            if not line:gap=True;continue
            if re.fullmatch(r'\[.*\]',line):
                if entries:section+=1
                label=line[1:-1].strip();has_labels=True;gap=False;continue
            if gap and entries:paragraph+=1
            entries.append((line,section,label,paragraph));gap=False
    matches=len(entries)==len(data) and all(normalized(e[0])==normalized(d['text']) for e,d in zip(entries,data))
    if matches and not has_labels:
        counts=Counter(e[3] for e in entries)
        use_paragraphs=any(n>1 for n in counts.values()) and len(counts)>1
        if use_paragraphs:entries=[(text,para,'Section '+str(para+1),para) for text,_,_,para in entries]
    for i,line in enumerate(data):
        if matches:
            _,identifier,name,_=entries[i]
            line['section_id']=identifier;line['section_label']=name or 'Song'
            line['section_source']='lyric labels' if has_labels else 'lyric paragraphs' if line['section_label']!='Song' else 'unspecified'
        else:
            line.setdefault('section_id',0);line.setdefault('section_label','Song');line.setdefault('section_source','unspecified')
    return data


def sections_for(data):
    sections=[]
    for i,line in enumerate(data):
        identifier=line.get('section_id',0)
        if not sections or identifier!=data[i-1].get('section_id',0):
            label=line.get('section_label','Song');role=next((r for r in ('verse','chorus','bridge','intro','outro','refrain') if r in label.lower()),'unknown')
            sections.append(dict(start=i,end=i+1,label=label,role=role,rhyme_scheme='unknown'))
        else:sections[-1]['end']=i+1
    return sections


def analyze(request,model,data):
    base=dict(sections=sections_for(data),source='lyric labels and text',lyric_form='unknown')
    if request is None:return base
    n=len(data)
    item=dict(type='object',properties=dict(start=dict(type='integer',minimum=0,maximum=n-1),end=dict(type='integer',minimum=1,maximum=n),label=dict(type='string'),role=dict(type='string',enum=['verse','chorus','bridge','intro','outro','refrain','unknown']),rhyme_scheme=dict(type='string')),required=['start','end','label','role','rhyme_scheme'],additionalProperties=False)
    payload=dict(model=model,think=False,stream=False,keep_alive=-1,format=dict(type='object',properties=dict(sections=dict(type='array',minItems=1,maxItems=n,items=item),lyric_form=dict(type='string')),required=['sections','lyric_form']),options=dict(num_ctx=8192,num_predict=2400,temperature=0),messages=[dict(role='system',content=(
        'Analyze song structure from these ordered lyric lines and existing section labels. '
        'Indices are zero based; end is EXCLUSIVE. Cover every line exactly once, in order. '
        'Keep every supplied explicit verse/chorus boundary. Identify refrains, short verse endings and repeated sections. '
        'Estimate each section rhyme scheme (for example AABBCCD) from the original language; use unknown when unsure. '
        'A rhyme pattern alone does not prove a verse boundary. Do not attach a verse closing line or refrain to the next verse. '
        'lyric_form describes inferred section repetition; use unknown if lyrics cannot establish it. '
        'Do not claim to analyze audio or melody. Return only schema-bound JSON.')),
        dict(role='user',content=json.dumps(dict(lines=[dict(index=i,text=line['text']) for i,line in enumerate(data)],known_sections=base['sections']),ensure_ascii=False))])
    try:
        response=request('chat',payload,timeout=900)
        if response.get('done_reason')=='length':raise ValueError('structure output truncated')
        result=json.loads(response.get('message',{}).get('content') or '{}')
        sections=result['sections'];cursor=0
        for section in sections:
            if type(section['start']) is not int or type(section['end']) is not int or section['start']!=cursor or not cursor<section['end']<=n:raise ValueError('noncontiguous lyric sections')
            if section['role'] not in ('verse','chorus','bridge','intro','outro','refrain','unknown'):raise ValueError('invalid section role')
            rhyme=section['rhyme_scheme']
            if rhyme!='unknown' and (not re.fullmatch('[A-Z?]+',rhyme) or len(rhyme)!=section['end']-cursor):raise ValueError('invalid rhyme scheme')
            cursor=section['end']
        if cursor!=n:raise ValueError('missing lyric lines')
        boundaries={s['start'] for s in base['sections']}
        if not boundaries<={s['start'] for s in sections}:raise ValueError('explicit verse boundary removed')
        return dict(sections=sections,source='AI interpretation of lyrics and labels',lyric_form=result.get('lyric_form','unknown'),model=model)
    except (ValueError,KeyError,TypeError,OSError) as exc:
        print('Structure analysis uncertain; preserving supplied lyric sections: '+str(exc),flush=True)
        return base


def grouped_lines(data,line_count,structure=None):
    sections=(structure or {}).get('sections') or sections_for(data)
    groups=[]
    repeats=Counter(normalized(line['text']) for line in data)
    for section in sections:
        pending=[]
        for index in range(section['start'],section['end']):
            refrain=repeats[normalized(data[index]['text'])]>1 and index>=section['end']-2
            if refrain and pending:groups.append(pending);pending=[]
            pending.append(index)
            if len(pending)>=line_count or refrain:groups.append(pending);pending=[]
        if pending:groups.append(pending)
    return groups


def group_contexts(data,groups,structure):
    result=[]
    for indices in groups:
        section=next(s for s in structure['sections'] if s['start']<=indices[0]<s['end'])
        result.append(dict(section=section['label'],role=section['role'],rhyme_scheme=section['rhyme_scheme'],
            verse_context=[line['text'] for line in data[section['start']:section['end']]],
            current_line_indices=indices))
    return result


def valid_line_groups(groups,count):
    return isinstance(groups,list) and all(isinstance(g,list) and g and all(type(i) is int for i in g) for g in groups) and [i for g in groups for i in g]==list(range(count))
