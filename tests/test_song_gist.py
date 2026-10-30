"""The whole-song reading is written once and reaches every scene request."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from direction.song_gist import attach_gist, song_gist


class SongGistTest(unittest.TestCase):
    def test_whole_song_is_read_in_one_request(self):
        calls = []

        def request(endpoint, payload, timeout):
            calls.append(json.loads(payload['messages'][1]['content']))
            return {'message': {'content': json.dumps({'subjects': ['People fail to connect while worshipping a neon god.']})}}

        gist = song_gist(request, 'test', ['Hello darkness, my old friend', 'And the people bowed and prayed'])
        self.assertIn('neon god', gist)
        self.assertEqual(len(calls), 1)
        self.assertIn('And the people bowed and prayed', calls[0][0]['lyrics'])

    def test_every_scene_input_carries_the_gist(self):
        payload = dict(messages=[dict(role='system', content='Write scenes.'),
                                 dict(role='user', content=json.dumps([dict(lyrics='a'), dict(lyrics='b')]))])
        attach_gist(payload, 'The song is about isolation.')
        inputs = json.loads(payload['messages'][1]['content'])
        self.assertEqual([entry['song_gist'] for entry in inputs], ['The song is about isolation.']*2)
        self.assertIn('song_gist', payload['messages'][0]['content'])


if __name__ == '__main__':
    unittest.main()
