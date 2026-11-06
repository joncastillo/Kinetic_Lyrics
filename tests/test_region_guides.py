import tempfile
import unittest
from pathlib import Path
from unittest import mock
from PIL import Image
from artwork.edit_regions import checked_regions, guide_image, guide_prompt
from artwork.maker import make
from models.image.catalog import model_spec

MODEL='Qwen/Qwen-Image-2.1'
REGIONS=[dict(x=.1,y=.2,w=.25,h=.3,instruction='Remove the watch'),dict(x=.6,y=.1,w=.2,h=.2,instruction='Change the hair')]


class RegionGuideTest(unittest.TestCase):
    def test_multiple_rectangles_are_validated_without_clipping_or_dropping_references(self):
        spec=model_spec(MODEL)
        self.assertEqual(checked_regions(REGIONS,'source.png',['source.png'],spec),REGIONS)
        for regions in ([dict(REGIONS[0],x=.9)], [dict(REGIONS[0],x=float('nan'))], REGIONS*7):
            with self.assertRaises(ValueError):checked_regions(regions,'source.png',['source.png'],spec)
        with self.assertRaisesRegex(ValueError,'reference slot'):
            checked_regions(REGIONS,'source.png',['source.png','a','b','c'],spec)
        with self.assertRaisesRegex(ValueError,'Qwen Image 2.1'):
            checked_regions(REGIONS,'source.png',['source.png'],model_spec('Qwen/Qwen-Image-Edit-2511'))

    def test_guide_leaves_clean_image_untouched_and_describes_each_region(self):
        source=Image.new('RGB',(400,300),'white');before=source.tobytes()
        guide=guide_image(source,REGIONS)
        self.assertEqual(source.tobytes(),before)
        self.assertNotEqual(guide.tobytes(),before)
        prompt=guide_prompt('Edit these details',REGIONS,1,3)
        self.assertIn('Reference image 3',prompt)
        self.assertIn('Region 2: Change the hair',prompt)
        self.assertIn('remove all guide markings',prompt)

    def test_real_generation_payload_includes_clean_source_then_guide_and_keeps_recipe(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'references').mkdir();Image.new('RGB',(512,512),'white').save(root/'references'/'source.png')
            (root/'history.json').write_text('[]')
            request=dict(template='none',prompt='Edit the selected areas',subject='',references=['source.png'],model=MODEL,width=512,height=512,
                format='png',quality=92,steps=2,seed=7,count=1,name='edited',folder=str(root/'out'),regions=REGIONS,region_source='source.png')
            pipe=mock.Mock(return_value=mock.Mock(images=[Image.new('RGB',(512,512))]))
            made=make(request,root,pipe,mock.Mock(),24,lambda *a:None)
            args=pipe.call_args.kwargs
            self.assertEqual(len(args['image']),2)
            self.assertEqual(args['image'][0].getpixel((51,102)),(255,255,255))
            self.assertNotEqual(args['image'][0].tobytes(),args['image'][1].tobytes())
            import json
            self.assertEqual(json.loads(Path(made[0]).with_suffix('.json').read_text())['regions'],REGIONS)
