"""Readable, complete local-LLM text traces captured by each Studio worker log."""

from contextlib import contextmanager
from contextvars import ContextVar
from itertools import count
import json
import threading

_STAGE = ContextVar("llm_trace_stage", default="Local LLM")
_IDS = count(1)
_OUTPUT = threading.Lock()


@contextmanager
def trace_stage(name):
    token = _STAGE.set(name)
    try:
        yield
    finally:
        _STAGE.reset(token)


def _block(title, text):
    print(f"\n[LLM {title} BEGIN]", flush=True)
    for line in str(text).splitlines() or [""]:
        for offset in range(0, max(1, len(line)), 4000):
            print("| " + line[offset : offset + 4000], flush=True)
    print(f"[LLM {title} END]", flush=True)


def log_request(payload):
    call_id = f'{_STAGE.get()} #{next(_IDS)} / {payload["model"]}'
    with _OUTPUT:
        print(f"\n[LLM REQUEST {call_id}]", flush=True)
        _block(
            f"{call_id} OPTIONS",
            json.dumps(payload.get("options", {}), ensure_ascii=False),
        )
        for index, message in enumerate(payload.get("messages", []), 1):
            _block(
                f'{call_id} {message.get("role", "message")} {index}',
                message.get("content", ""),
            )
            if message.get("images"):
                print(
                    f'[LLM {call_id}: {len(message["images"])} attached image(s); image bytes omitted]',
                    flush=True,
                )
    return call_id


def log_response(call_id, response):
    message = response.get("message", {})
    with _OUTPUT:
        if message.get("thinking"):
            _block(f"MODEL THINKING {call_id}", message["thinking"])
        _block(f"RESPONSE {call_id}", message.get("content", ""))
        if message.get("tool_calls"):
            _block(
                f"TOOL CALLS {call_id}",
                json.dumps(message["tool_calls"], ensure_ascii=False),
            )
        print(
            f'[LLM {call_id} done_reason={response.get("done_reason", "unknown")} '
            f'input_tokens={response.get("prompt_eval_count", "unknown")} '
            f'output_tokens={response.get("eval_count", "unknown")}]',
            flush=True,
        )


def log_failure(call_id, error):
    with _OUTPUT:
        _block(f"ERROR {call_id}", str(error))
