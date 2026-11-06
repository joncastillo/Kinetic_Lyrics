import unittest
from direction.story import retime_story


class SongDurationTest(unittest.TestCase):

    def test_retiming_keeps_late_actions_and_exact_song_end(self):
        story=dict(segments=[dict(index=0,start=0,seconds=20,characters='Doctor',environment='Lab',camera='hold',
            beats=[dict(start=0,end=10,action='Open the notebook'),dict(start=10,end=20,action='Close the notebook')])])
        self.assertTrue(retime_story(story,[(0,9.192)]))
        segment=story['segments'][0]
        self.assertEqual(segment['seconds'],9.192)
        self.assertEqual(segment['beats'][-1]['end'],9.192)
        self.assertEqual([b['action'] for b in segment['beats']],['Open the notebook','Close the notebook'])
        self.assertFalse(retime_story(story,[(0,9.192)]))
