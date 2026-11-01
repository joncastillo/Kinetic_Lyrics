"""Score-based artwork acceptance shared by the studio and worker."""
import re
DEFAULT_THRESHOLD = 50
MAX_AUTO_REPAIRS = 5
CANDIDATES_PER_REPAIR = 3
ANATOMY_TERMS = (r'\b(?:hand|finger|thumb|digit|wrist|palm|knuckle|limb|arm|leg|knee|elbow|foot|feet|appendage|polydactyl|'
                 r'moustache|mustache|beard|stubble|goatee|facial hair)')


def reported_defect(text):
    """Count asserted defects, not phrases such as 'no extra fingers'."""
    terms=(r'\b(?:six (?:digit|finger)|extra (?:digit|finger|thumb|limb|arm|leg|hand|foot|feet|appendage)|abnormal appendage|'
           r'polydactyly|duplicated (?:limb|arm|leg)|fused (?:finger|limb|arm|leg)|third (?:arm|leg|hand)|'
           r'merged (?:limb|arm|leg)s?|missing (?:arm|leg|hand|foot)|backwards? (?:knee|elbow|leg|arm)|'
           r'(?:knee|elbow)s? bend(?:s|ing)? backwards?|impossibly bent|dislocated (?:limb|arm|leg)|disconnected (?:limb|arm|leg|hand))\w*\b')
    for clause in re.split(r'[,;.!?\n]|\b(?:but|however|yet)\b',str(text).lower()):
        for match in re.finditer(terms,clause):
            before=' '.join(clause[:match.start()].split()[-6:])
            after=' '.join(clause[match.end():].split()[:4])
            if re.search(r'\b(?:no|not|without|neither|absence|absent|uncertain|possible|possibly|unclear|might|may)\b',before):continue
            if re.match(r'\s*(?:are |is |were |was )?(?:not (?:present|visible|seen)|absent|not detected)\b',after):continue
            if re.search(r'\b(?:hidden|occluded|unseen)\b|not visible|out of view',after):continue
            return True
    return False

FEMALE = r'\b(?:woman|women|female|girl|lady|mother|bride|she|her)\b'
FACIAL_HAIR = r'\b(?:moustache|mustache|beard|stubble|goatee|facial hair|sideburns)\w*\b'


def female_facial_hair(text):
    """Whether a review sentence asserts facial hair on a woman, not 'the woman has no beard'."""
    for clause in re.split(r'[;.!?\n]|\b(?:but|however|yet)\b', str(text).lower()):
        if not re.search(FEMALE, clause):continue
        for match in re.finditer(FACIAL_HAIR, clause):
            before = ' '.join(clause[:match.start()].split()[-5:])
            if re.search(r'\b(?:no|not|without|free of|lacks?|absent|smooth)\b', before):continue
            if re.match(r'\s*(?:is |are )?(?:absent|not (?:present|visible))', clause[match.end():]):continue
            if match.group(0).endswith('less'):continue  # beardless
            return True
    return False


def figure_defect(check):
    """A confident figure check that shows wrong limbs or a woman with facial hair."""
    if not isinstance(check, dict) or check.get('uncertain'):return False
    if check.get('limbs_correct') is False:return True
    if check.get('apparent_gender') == 'female' and check.get('facial_hair') is True:return True
    if any(type(check.get(key)) is int and check[key] > 2 for key in ('visible_arms', 'visible_legs')):return True
    return reported_defect(check.get('assessment', '')) or female_facial_hair(check.get('assessment', ''))


def anatomy_defect(review):
    for check in review.get('hand_checks', []):
        if not isinstance(check,dict) or check.get('uncertain'):continue
        if type(check.get('visible_fingers')) is int and check['visible_fingers'] > 5:
            return True
        if reported_defect(check.get('assessment','')):
            return True
    if any(figure_defect(check) for check in review.get('figure_checks', [])):
        return True
    for issue in review.get('issues', []):
        if isinstance(issue,dict) and (reported_defect(issue.get('issue','')) or female_facial_hair(issue.get('issue',''))):
            return True
    return False

def rejected(review, threshold=DEFAULT_THRESHOLD):
    if review.get('validation_pending'):return True
    score = review.get('score')
    if not (type(score) in (int, float) and 0 <= score <= 100):
        return False
    return anatomy_defect(review) or score < threshold

def anatomy_only(review):
    """Extra digits or limbs with no other substantial issue: a new seed fixes these, a new scene is unnecessary."""
    if review.get('validation_pending') or not anatomy_defect(review):return False
    return not any(isinstance(issue,dict) and issue.get('severity') in ('medium','high')
                   and not re.search(ANATOMY_TERMS,str(issue.get('issue','')),re.I)
                   for issue in review.get('issues',[]))

def repair_instruction(review):
    issues='; '.join(str(i.get('issue',''))+' at '+str(i.get('location','')) for i in review.get('issues',[]) if isinstance(i,dict))
    return ('Correct these observed defects while preserving the original subject, style and composition: '
            +(issues or review.get('summary','Improve the visible quality.'))+
            '. Use a coherent, natural silhouette. Human anatomy requirements apply only if people or body parts are requested. '
            'Do not add people, faces or hair to an object study.')
