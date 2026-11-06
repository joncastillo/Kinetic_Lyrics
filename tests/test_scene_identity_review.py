import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from models.vision.scene_review import context_for, extend, validate, apply_verdict
from models.vision.policy import rejected
from models.vision.response import request_review, ReviewUnavailable


class SceneIdentityReviewTest(unittest.TestCase):
    def test_verifier_receives_named_character_picture_and_context_changes_with_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);reference=root/'doctor.png';Image.new('RGB',(20,20),'red').save(reference)
            (root/'story.json').write_text(json.dumps(dict(segments=[dict(index=2,moment='Doctor uses a pipette',characters='Doctor watches the pipette',beats=[])],
                entities=[dict(id='doctor',name='Dr. Viktoria',kind='character',cast=True,segments=[2],image=str(reference))])))
            context=context_for(root/'illustrations.json',2)
            payload=dict(messages=[dict(content='Review',images=['candidate'])],format=dict(properties={},required=[]),options={})
            extend(payload,context)
            self.assertEqual(len(payload['messages'][0]['images']),2)
            self.assertIn('Dr. Viktoria',payload['messages'][0]['content'])
            self.assertIn('Direct-to-camera gaze is allowed if explicitly requested',payload['messages'][0]['content'])
            Image.new('RGB',(20,20),'blue').save(reference)
            self.assertNotEqual(context_for(root/'illustrations.json',2)['signature'],context['signature'])

    def test_clear_likeness_or_gaze_failure_rejects_even_high_score(self):
        for scene,characters in [(dict(matches=True,pose_gaze_matches=True,evidence='Scene matches',uncertain=False),[dict(id='doctor',name='Doctor',matches=False,evidence='Wrong face and hair',uncertain=False)]),
                                 (dict(matches=True,pose_gaze_matches=False,evidence='Unrequested portrait gaze replaces the task',uncertain=False),[])]:
            result=dict(score=99,uncertain=False,issues=[],scene_check=scene,character_checks=characters)
            apply_verdict(result)
            self.assertTrue(rejected(result))
            self.assertEqual(result['issues'][0]['severity'],'high')

    def test_unseen_faces_are_uncertain_and_missing_checks_cannot_pass(self):
        context=dict(characters=[dict(id='doctor',path='')])
        result=dict(score=80,uncertain=False,issues=[],scene_check=dict(matches=True,pose_gaze_matches=None,evidence='Eyes too small',uncertain=True),
                    character_checks=[dict(id='doctor',name='Doctor',matches=None,evidence='Reference unavailable',uncertain=True)])
        validate(result,context);apply_verdict(result)
        self.assertTrue(result['uncertain']);self.assertFalse(rejected(result))
        with self.assertRaises(ValueError):validate(dict(result,character_checks=[]),context)
        result['character_checks'][0]['matches']=True
        with self.assertRaises(ValueError):validate(result,context)

    def test_looping_verifier_retries_warmer_without_increasing_output_budget(self):
        sent=[]
        def request(query):sent.append(query);return dict(done_reason='length',message=dict(content=''))
        with self.assertRaises(ReviewUnavailable):
            request_review(request,dict(model='vl',format=dict(type='object'),messages=[dict(role='user',content='Review')]))
        self.assertEqual([q['options']['num_predict'] for q in sent],[4096,4096])
        self.assertGreater(sent[1]['options']['temperature'],sent[0]['options']['temperature'])
