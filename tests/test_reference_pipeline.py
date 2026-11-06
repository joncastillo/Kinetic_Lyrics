"""The artwork run's order: every reference picture first, checked (and painted again) before any illustration."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent/'src'))

from direction.entities import SHEET_VERSION  # noqa: E402
from studio import worker  # noqa: E402


class ReferencePipelineTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        folder = self.root/'video.artwork'/'abc'
        folder.mkdir(parents=True)
        self.manifest = folder/'illustrations.json'
        self.manifest.write_text(json.dumps(dict(prompts=['a', 'b', 'c'], model='Qwen/Qwen-Image-2.1', style_prompt='ink')),
                                 encoding='utf-8')
        painted = folder/'entities'/'the-hive.png'
        painted.parent.mkdir()
        painted.write_bytes(b'sheet')
        (folder/'story.json').write_text(json.dumps(dict(segments=[], entities=[
            dict(id='the-hive', name='the hive', kind='place', looks='A dark chamber.', segments=[0, 2], image=str(painted),
                 sheet_version=SHEET_VERSION),
            dict(id='the-street', name='the street', kind='place', looks='A wet street.', segments=[1]),
            dict(id='the-criminal', name='the criminal', kind='character', looks='A man.', segments=[1, 2]),
            dict(id='elara', name='Elara', kind='character', looks='A woman.', segments=[0], cast=True),
            dict(id='mood', name='the mood', kind='mood', looks='Dread.', segments=[0, 1, 2])])), encoding='utf-8')
        (self.root/'config.json').write_text(json.dumps(dict(vision_model='qwen3-vl:8b', ai_model='auto')), encoding='utf-8')







    def test_the_sheet_job_uses_the_end_frame_models_own_steps(self):
        job = json.dumps(dict(prompts=['a'], model='krea/Krea-2-Turbo', steps=8))
        self.manifest.write_text(job, encoding='utf-8')
        with mock.patch('artwork.generation.run_job') as run:
            worker.paint_references(self.root, self.manifest, ['x'], 'cache', model='Qwen/Qwen-Image-2.1')
        sheet = json.loads(run.call_args.args[0].read_text(encoding='utf-8'))
        self.assertEqual((sheet['model'], sheet['steps'], sheet['paint_references']), ('Qwen/Qwen-Image-2.1', 40, ['x']))

    def test_every_pictured_reference_without_a_picture_is_painted_before_the_scenes(self):
        from studio import worker

        with mock.patch.object(worker, 'paint_references') as paint, mock.patch.object(worker, 'emit'):
            worker.paint_all_references(self.root, self.manifest, {}, 'cache')
        paint.assert_called_once()
        self.assertEqual(sorted(paint.call_args.args[2]), ['elara', 'the-criminal', 'the-street'])   # not the painted hive, nor the mood

    def test_greenscreen_scenery_paints_objects_only(self):
        from studio import worker

        job = json.loads(self.manifest.read_text(encoding='utf-8'))
        self.manifest.write_text(json.dumps(dict(job, artwork_mode='matte')), encoding='utf-8')
        with mock.patch.object(worker, 'paint_references') as paint, mock.patch.object(worker, 'emit'):
            worker.paint_all_references(self.root, self.manifest, {}, 'cache')
        paint.assert_not_called()

    def test_failed_references_are_painted_and_checked_again_up_to_the_rounds(self):
        from studio import worker

        verdicts = iter([['the-hive'], ['the-hive'], []])   # fails twice, then passes
        with mock.patch('models.vision.sheet_review.review_references', side_effect=lambda *a, **k: next(verdicts)) as review, \
                mock.patch.object(worker, 'paint_references') as paint, mock.patch.object(worker, 'emit') as emit, \
                mock.patch('artwork.queue.update_queue') as queue:
            (self.manifest.parent/'000.png').write_bytes(b'scene')   # already painted with the failed hive
            worker.check_references(self.root, self.manifest, dict(vision_model='qwen3-vl:8b'), 'cache', rounds=3)
        self.assertEqual(paint.call_count, 2)
        self.assertEqual(review.call_count, 3)
        self.assertEqual(review.call_args_list[0].kwargs['max_repaints'], 3)
        self.assertEqual([c.args[0] for c in emit.call_args_list][0], 'reference-check')
        queued = [c.kwargs['append'] for c in queue.call_args_list]
        self.assertEqual([(q['index'], q['reason']) for q in queued], [(0, 'reference')])   # scene 2 is not painted yet

    def test_the_last_round_records_the_verdict_and_stops(self):
        from studio import worker

        with mock.patch('models.vision.sheet_review.review_references', return_value=['the-hive']) as review, \
                mock.patch.object(worker, 'paint_references') as paint, mock.patch.object(worker, 'emit'), \
                mock.patch('artwork.queue.update_queue'):
            worker.check_references(self.root, self.manifest, dict(vision_model='qwen3-vl:8b'), 'cache', rounds=2)
        self.assertEqual(paint.call_count, 2)
        self.assertEqual(review.call_count, 3)
        self.assertFalse(review.call_args_list[-1].kwargs['repaint'])

    def test_the_run_paints_and_checks_references_before_the_illustrations(self):
        from studio import worker

        order = []
        with mock.patch.object(worker, 'paint_all_references', side_effect=lambda *a: order.append('references')), \
                mock.patch.object(worker, 'check_references', side_effect=lambda *a, **k: order.append('check')), \
                mock.patch('artwork.generation.run_job', side_effect=lambda *a: order.append('illustrations')), \
                mock.patch('models.gpu.lifecycle.ModelSession'), mock.patch('artwork.queue.claim_queue', return_value=[]), \
                mock.patch('artwork.queue.has_pending', return_value=False), mock.patch.object(worker, 'emit'):
            worker.generate_and_review(self.manifest, 'cache')
        self.assertEqual(order, ['references', 'check', 'illustrations'])


if __name__ == '__main__':
    unittest.main()
