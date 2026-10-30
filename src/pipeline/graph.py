"""The video pipeline as a LangGraph state graph with a checkpoint in each project folder.

    probe -> align -> analyse -+-> illustrate -> request_review -> review -> direct -> render -> finish
                               |        (skipped when no review is needed)   ^          |
                               |                                             '-(queued replacements)
                               '-> subtitles                              (legacy ASS renderer)

Each node saves its result in the checkpoint (`<output>.graph.sqlite`), so a failed run started
again with --resume continues from the step that failed instead of from the beginning. Artwork
review is a LangGraph interrupt: the run pauses there until Studio writes `artwork-approved`.

The parsed command line travels as the run context rather than in the state, so it is never
saved; the state holds only what the steps produce, and `options` copies those results back onto
the command-line options that the existing step functions read.
"""
from __future__ import annotations

from dataclasses import dataclass
import argparse
import json
import math
from pathlib import Path
import time
from typing import Optional, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from core.progress import emit

APPROVAL = 'artwork-approved'
# Step results that the step functions read back from the command-line options.
CARRIED = ('melody', 'rhythm', 'illustrations', 'review_artwork', 'image_seed', 'illustration_lines', 'instruments_found')


class PipelineState(TypedDict, total=False):
    audio: str
    audio_digest: Optional[str]
    output: str
    duration: float
    lines: Optional[list]
    data: list
    theme: dict
    melody: Optional[dict]
    rhythm: Optional[dict]
    illustrations: Optional[list]
    review_artwork: bool
    image_seed: int
    illustration_lines: int
    instruments_found: Optional[list]
    plan: dict
    replacements_pending: bool


@dataclass
class Run:
    args: argparse.Namespace


def options(state, runtime):
    """The command-line options with every step result so far applied, as the step functions expect."""
    args = runtime.context.args
    for key in CARRIED:
        if key in state:
            value = state[key]
            setattr(args, key, [Path(p) for p in value] if key == 'illustrations' and value else value)
    return args


def paths(state):
    output = Path(state['output'])
    return dict(output=output, timings=output.with_suffix('.timings.json'), theme=output.with_suffix('.theme.json'),
                design=output.with_suffix('.design.json'), lyrics=output.with_suffix('.lyrics.txt'),
                ass=output.with_suffix('.ass'), ocr=output.with_suffix('.ocr.json'))


def probe(state, runtime: Runtime[Run]):
    from core.process import run as run_command
    from pipeline.timing import lyrics_lines
    args = options(state, runtime)
    for reference in args.style_reference or []:
        from PIL import Image
        with Image.open(reference) as image:
            image.verify()
    duration = float(run_command(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                '-of', 'default=noprint_wrappers=1:nokey=1', state['audio']]).strip())
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Audio duration must be finite and positive.')
    return dict(duration=duration, lines=lyrics_lines(args.lyrics) if args.lyrics else None)


def align(state, runtime: Runtime[Run]):
    from models.speech.recognition import align as align_lyrics, transcribe
    from pipeline.timing import repair_zero_durations, validate
    args = options(state, runtime)
    lines = state['lines']
    source = (args.alignment_audio or Path(state['audio'])).resolve()
    emit('alignment', 0, message='Aligning supplied lyrics' if lines is not None else 'Transcribing lyrics from audio')
    if args.timings:
        data = json.loads(args.timings.read_text(encoding='utf-8-sig'))
    elif lines is not None:
        data = align_lyrics(source, lines, args)
    else:
        data = transcribe(source, args)
    if lines is None:
        lines = [line['text'] for line in data]
        if not lines:
            raise ValueError('No lyric lines were found in the timing data.')
    repaired = repair_zero_durations(data, state['duration'])
    timings = paths(state)['timings']
    if args.timings and repaired and timings.exists():
        timings.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    validate(data, lines, state['duration'])
    return dict(data=data, lines=lines)


def analyse(state, runtime: Runtime[Run]):
    from direction.theme import theme_for
    args = options(state, runtime)
    data, lines, files = state['data'], state['lines'], paths(state)
    output = files['output']
    from audio.onsets import refine_line_starts
    emit('alignment', .95, message='Measuring where each line is sung')
    moved = refine_line_starts(data, Path(state['audio']), output.parent)
    from audio.melody import ensure_melody
    melody = ensure_melody(data, output.parent)
    from audio.rhythm import ensure_rhythm
    rhythm = ensure_rhythm(Path(state['audio']), output.parent)
    found = None
    if getattr(args, 'instruments', 'off') != 'off':
        from audio.instruments import ensure_instruments
        found = ensure_instruments(Path(state['audio']), output.parent, state['duration'], getattr(args, 'image_cache', None))
    if moved:
        print(f'Moved {moved} line start(s) to the measured vocal onset.', flush=True)
        from pipeline.timing import repair_zero_durations, validate
        repair_zero_durations(data, state['duration'])
        validate(data, lines, state['duration'])
        files['timings'].write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    from direction.song_structure import annotate_sections
    annotate_sections(data, args.lyrics)
    if args.illustration_lines == 'auto':
        from direction.image_grouping import estimate_lines
        emit('direction', 0, message='Choosing how many lyric lines each image should cover')
        args.illustration_lines = estimate_lines(data, args.ai_model)
        studio_config = output.parent/'config.json'
        if studio_config.is_file():
            saved = json.loads(studio_config.read_text(encoding='utf-8'))
            saved['illustration_lines'] = args.illustration_lines
            saved['illustration_lines_mode'] = 'auto'
            studio_config.write_text(json.dumps(saved, indent=2), encoding='utf-8')
    emit('alignment', 1, message='Lyric timing validated')
    theme = theme_for(args.theme)
    print(f"Theme: {theme['name']}; {len(lines)} lines; {state['duration']:.1f}s", flush=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.lyrics is None:
        files['lyrics'].write_text('\n'.join(lines)+'\n', encoding='utf-8')
        print(f"Saved recovered lyrics: {files['lyrics']}", flush=True)
    if not args.timings:
        files['timings'].write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    files['theme'].write_text(json.dumps(dict(prompt=args.theme, cinematic=args.cinematic, **theme), indent=2), encoding='utf-8')
    return dict(data=data, theme=theme, melody=melody, rhythm=rhythm, instruments_found=found,
                illustration_lines=args.illustration_lines)


def renderer(state, runtime: Runtime[Run]):
    return 'illustrate' if runtime.context.args.renderer == 'editorial' else 'subtitles'


def illustrate(state, runtime: Runtime[Run]):
    args = options(state, runtime)
    if not args.no_illustrations and args.illustrations is None:
        from pipeline.illustrations import generate
        output = paths(state)['output']
        args.illustrations = generate(state['data'], output.parent/(output.stem+'.artwork'), args)
    if args.illustrations:
        print('Illustration panels: ' + ', '.join(str(p) for p in args.illustrations), flush=True)
    else:
        print('Illustration panels: none (typography only).', flush=True)
    # generate() may adopt the saved seed and line grouping and decide that the artwork needs review.
    return dict(illustrations=[str(p) for p in args.illustrations] if args.illustrations else None,
                review_artwork=bool(args.review_artwork), image_seed=args.image_seed,
                illustration_lines=args.illustration_lines)


def needs_review(state, runtime: Runtime[Run]):
    return 'request_review' if state.get('illustrations') and state.get('review_artwork') else 'direct'


def request_review(state, runtime: Runtime[Run]):
    (paths(state)['output'].parent/APPROVAL).unlink(missing_ok=True)
    emit('review', 0, message='Review illustrations, then approve to render')
    return {}


def review(state, runtime: Runtime[Run]):
    """Pause the run until the artwork is approved; `run` resumes it."""
    interrupt(dict(waiting_for=str(paths(state)['output'].parent/APPROVAL)))
    return {}


def direct(state, runtime: Runtime[Run]):
    args = options(state, runtime)
    data = state['data']
    from direction.typography import direct as plan_typography, validate_plan
    emit('direction', 0, message='Planning typography and motion')
    plan = (validate_plan(json.loads(args.plan.read_text(encoding='utf-8-sig')), data)
            if args.plan else plan_typography(data, state['theme'], args.theme, args.ai_model, args.director, seed=args.image_seed))
    if args.text_animation == 'ai':
        from direction.animation import ensure_word_direction
        plan = ensure_word_direction(data, plan, vars(args))
    if not args.plan or args.text_animation == 'ai':
        paths(state)['design'].write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Design: {plan.get('concept', 'Custom editorial plan')}", flush=True)
    emit('direction', 1, message='Typography plan ready')
    return dict(plan=plan)


def render(state, runtime: Runtime[Run]):
    args = options(state, runtime)
    output = paths(state)['output']
    from artwork.queue import before_video_render, ReplacementsPending
    from render.compositor import render as render_video
    before_video_render(output, args)
    try:
        render_video(Path(state['audio']), output, state['data'], state['plan'], state['duration'], args)
    except ReplacementsPending:
        emit('illustrations', 1, message='Pausing video render for queued image replacements')
        return dict(replacements_pending=True)
    return dict(replacements_pending=False)


def rendered(state, runtime: Runtime[Run]):
    return 'render' if state.get('replacements_pending') else 'finish'


def finish(state, runtime: Runtime[Run]):
    from models.ocr.video import validate_ocr
    from render.subtitles import archive_legacy_subtitles
    args = options(state, runtime)
    files = paths(state)
    archive_legacy_subtitles(files['ass'])
    print(f"Saved {files['output']}\nArt direction: {args.plan or files['design']}\nTiming source: {args.timings or files['timings']}")
    if args.validate_ocr:
        validate_ocr(files['output'], state['data'], state['duration'], files['ocr'])
    emit('complete', 1, message='Video ready')
    return {}


def subtitles(state, runtime: Runtime[Run]):
    from models.ocr.video import validate_ocr
    from render.subtitles import render_subtitles
    args = options(state, runtime)
    files = paths(state)
    render_subtitles(Path(state['audio']), files['output'], files['ass'], state['data'], state['duration'], state['theme'], args)
    print(f"Saved {files['output']}\nAnimation: {files['ass']}\nTiming source: {args.timings or files['timings']}")
    if args.validate_ocr:
        validate_ocr(files['output'], state['data'], state['duration'], files['ocr'])
    return {}


def build():
    graph = StateGraph(PipelineState, context_schema=Run)
    for node in (probe, align, analyse, illustrate, request_review, review, direct, render, finish, subtitles):
        graph.add_node(node.__name__, node)
    graph.add_edge(START, 'probe')
    graph.add_edge('probe', 'align')
    graph.add_edge('align', 'analyse')
    graph.add_conditional_edges('analyse', renderer, ['illustrate', 'subtitles'])
    graph.add_conditional_edges('illustrate', needs_review, ['request_review', 'direct'])
    graph.add_edge('request_review', 'review')
    graph.add_edge('review', 'direct')
    graph.add_edge('direct', 'render')
    graph.add_conditional_edges('render', rendered, ['render', 'finish'])
    graph.add_edge('finish', END)
    graph.add_edge('subtitles', END)
    return graph


def checkpoint_path(output):
    return Path(output).with_suffix('.graph.sqlite')


def run(args, audio, output, resume=False, poll=.5):
    """Run (or with `resume`, continue) the pipeline for one output video."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    thread = dict(configurable=dict(thread_id=str(output)))
    context = Run(args)
    from core.files import file_digest
    digest = file_digest(audio)
    with SqliteSaver.from_conn_string(str(checkpoint_path(output))) as saver:
        graph = build().compile(checkpointer=saver)
        snapshot = graph.get_state(thread)
        # A replaced track (even under the same file name) starts again from the beginning.
        unfinished = bool(snapshot.next) and snapshot.values.get('audio') == str(audio) and snapshot.values.get('audio_digest') == digest
        if resume and unfinished:
            print(f"Resuming from saved step: {', '.join(snapshot.next)}", flush=True)
            payload = None
        else:
            saver.delete_thread(str(output))
            payload = dict(audio=str(audio), audio_digest=digest, output=str(output))
        while True:
            graph.invoke(payload, thread, context=context)
            snapshot = graph.get_state(thread)
            if not snapshot.interrupts:
                return snapshot.values
            approval = output.parent/APPROVAL
            while not approval.exists():
                time.sleep(poll)
            payload = Command(resume=True)
