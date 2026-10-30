"""Validate model review output and retry incomplete replies within the same batch."""
import copy
import json
import re


class ReviewUnavailable(ValueError):
    """Bounded validation attempts failed; retain artwork for manual review."""


def parse_review(response):
    if not isinstance(response,dict):raise ValueError('model response is not an object')
    message=response.get('message')
    content=message.get('content') if isinstance(message,dict) else None
    if not isinstance(content,str) or not content.strip():
        if response.get('done_reason')=='length':raise ValueError('model reached its output token limit before final JSON')
        raise ValueError('model returned an empty review')
    content=content.strip()
    fenced=re.fullmatch(r'```(?:json)?\s*(.*?)\s*```',content,re.S|re.I)
    if fenced:content=fenced.group(1)
    try:result=json.loads(content)
    except json.JSONDecodeError as exc:raise ValueError(f'model returned invalid review JSON at character {exc.pos}') from exc
    if not isinstance(result,dict) or not isinstance(result.get('summary'),str) or not result['summary'].strip():
        raise ValueError('review needs a nonempty summary')
    if type(result.get('score')) is not int or not 0<=result['score']<=100:
        raise ValueError('review needs an integer score from 0 to 100')
    if type(result.get('uncertain')) is not bool:raise ValueError('review needs an uncertainty flag')
    issues=result.get('issues');hands=result.get('hand_checks')
    if not isinstance(issues,list) or any(not isinstance(i,dict) or not isinstance(i.get('issue'),str)
        or i.get('severity') not in ('low','medium','high') or not isinstance(i.get('location'),str) for i in issues):
        raise ValueError('review contains invalid issue evidence')
    if not isinstance(hands,list) or any(not isinstance(h,dict) or not isinstance(h.get('hand'),str)
        or not isinstance(h.get('assessment'),str) or type(h.get('uncertain')) is not bool
        or 'visible_fingers' not in h
        or (h.get('visible_fingers') is not None and (type(h['visible_fingers']) is not int or not 0<=h['visible_fingers']<=20)) for h in hands):
        raise ValueError('review contains invalid hand evidence')
    return result


def request_review(request,payload,notify=None):
    query=copy.deepcopy(payload)
    query['messages'][0]['content']+=(
        '\nReturn only one concise JSON object matching this schema. Use empty arrays when there '
        'are no visible issues or hands. Keep each assessment under 35 words. JSON schema: '
        +json.dumps(query['format'],separators=(',',':')))
    last=None
    for attempt,budget in enumerate((4096,6144)):
        expanded=attempt>0 and last is not None and 'output token limit' in str(last)
        query['options']={**query.get('options',{}),'temperature':0,'num_predict':8192 if expanded else budget}
        if expanded:query['options']['num_ctx']=max(16384,query['options'].get('num_ctx',8192))
        response=request(copy.deepcopy(query))
        try:return parse_review(response)
        except ValueError as exc:
            last=exc
            if attempt==0:
                query['messages'][0]['content']=payload['messages'][0]['content']+(
                    '\nReturn the final JSON immediately. Use a short summary and at most three evidenced issues. '
                    'Use empty hand_checks when no hands are visible. No commentary or extended reasoning.')
                if notify:notify(f'{query["model"]}: {exc}; retrying this review once with concise final JSON')
    raise ReviewUnavailable(f'{query["model"]} could not return a usable review after 2 attempts: {last}. '
                     'Generated images are saved; resume from image review to retry validation.') from last
