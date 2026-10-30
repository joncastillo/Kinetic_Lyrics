"""Repair policy: anatomy-only failures are reseeded without a new prompt."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from review_policy import anatomy_only, CANDIDATES_PER_REPAIR

SIX_FINGERS = dict(score=20, summary='', uncertain=False, issues=[
    dict(issue='Six fingers on the left hand', severity='high', location='left')],
    hand_checks=[dict(hand='left', visible_fingers=6, assessment='six fingers', uncertain=False)])


class AnatomyOnlyTest(unittest.TestCase):
    def test_hand_defect_alone(self):
        self.assertTrue(anatomy_only(SIX_FINGERS))

    def test_hand_defect_with_scene_problem(self):
        review = dict(SIX_FINGERS, issues=SIX_FINGERS['issues']+[
            dict(issue='Lamp head floats halfway up the pole', severity='high', location='right')])
        self.assertFalse(anatomy_only(review))

    def test_minor_other_issue_still_reseeds(self):
        review = dict(SIX_FINGERS, issues=SIX_FINGERS['issues']+[
            dict(issue='Slightly flat shading', severity='low', location='sky')])
        self.assertTrue(anatomy_only(review))

    def test_scene_problem_without_hands(self):
        self.assertFalse(anatomy_only(dict(score=30, issues=[
            dict(issue='Missing focal subject', severity='high', location='center')], hand_checks=[])))


class RepairBatchTest(unittest.TestCase):
    def test_reseeds_and_keeps_first_passing_candidate(self):
        import studio_batches
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = root/'artwork'/'key'/'illustrations.json'
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps(dict(prompts=['a dancer'], groups=['lyric'])), encoding='utf-8')
            (root/'config.json').write_text(json.dumps(dict(style_prompt='ink', image_cache=str(root/'cache'))), encoding='utf-8')
            target = manifest.parent/'000.png'
            target.write_bytes(b'original')
            sha = hashlib.sha256(b'original').hexdigest()
            review = dict(SIX_FINGERS, image_sha256=sha)
            generated, reviewed, events = [], [], []

            def generate_candidate(root_, job, index, cache, prompt):
                path = root/'candidates'/f'{len(generated)}.png'
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(str(len(generated)).encode())
                generated.append(prompt)
                return path

            def vision_review(path, *args):
                reviewed.append(path.name)
                score = 80 if path.name == '1.png' else 20
                return dict(SIX_FINGERS if score < 50 else dict(score=score, issues=[], hand_checks=[]),
                            image_sha256=hashlib.sha256(path.read_bytes()).hexdigest())

            worker = SimpleNamespace(generate_candidate=generate_candidate, vision_review=vision_review,
                                     emit=lambda *a, **k: events.append(k))
            studio_batches.repair_batch(worker, root, manifest,
                                        [dict(index=0, model='vision', expected_sha=sha, review=review)])
            self.assertEqual(generated, ['a dancer']*CANDIDATES_PER_REPAIR)
            self.assertEqual(reviewed, ['0.png', '1.png'])
            self.assertEqual(target.read_bytes(), b'1')
            self.assertTrue(any(e.get('repaired') for e in events))

    def test_scene_problem_writes_every_rounds_prompts_once(self):
        import studio_batches
        from unittest import mock
        from review_policy import MAX_AUTO_REPAIRS
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = root/'artwork'/'key'/'illustrations.json'
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps(dict(prompts=['a lamp'], groups=['lyric'])), encoding='utf-8')
            (root/'config.json').write_text(json.dumps(dict(style_prompt='ink', image_cache=str(root/'cache'))), encoding='utf-8')
            target = manifest.parent/'000.png'
            target.write_bytes(b'original')
            sha = hashlib.sha256(b'original').hexdigest()
            scene = dict(score=30, issues=[dict(issue='Lamp head floats halfway up the pole', severity='high', location='left')],
                         hand_checks=[], image_sha256=sha)
            generated = []

            def generate_candidate(root_, job, index, cache, prompt):
                path = root/'candidates'/f'{len(generated)}.png'
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(str(len(generated)).encode())
                generated.append(prompt)
                return path

            def revise(worker, job, config, items, variants=1):
                return {item['index']: [dict(job, prompts=[f'fresh {v}']) for v in range(variants)] for item in items}

            worker = SimpleNamespace(generate_candidate=generate_candidate, emit=lambda *a, **k: None,
                                     vision_review=lambda path, *a: dict(scene, image_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            with mock.patch('prompt_repair.revise_repair_prompts', side_effect=revise) as revised:
                studio_batches.repair_batch(worker, root, manifest, [dict(index=0, model='vision', expected_sha=sha, review=scene)])
            revised.assert_called_once()
            self.assertEqual(revised.call_args.kwargs['variants'], MAX_AUTO_REPAIRS)
            self.assertEqual(generated, ['fresh 0']*CANDIDATES_PER_REPAIR+['fresh 1']*CANDIDATES_PER_REPAIR)


if __name__ == '__main__':
    unittest.main()
