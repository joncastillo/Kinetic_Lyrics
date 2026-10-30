"""YouTube intake uses one video and ranks several lyric providers."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))


class Response:
    def __init__(self, data=None, text=''):
        self.data, self.text = data, text

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class Session:
    def get(self, url, **kwargs):
        if 'lrclib.net/api/search' in url:
            return Response([dict(id=17, trackName='Sky Song', artistName='Singer',
                                  plainLyrics='First verse here\n'+('Sing to the sky\n'*8), duration=123)])
        if 'genius.com/api/search/multi' in url:
            return Response(dict(response=dict(sections=[dict(hits=[dict(type='song', result=dict(
                url='https://genius.com/Singer-sky-song-lyrics', title='Sky Song',
                primary_artist=dict(name='Singer')))])])))
        if 'genius.com/Singer' in url:
            return Response(text='<div data-lyrics-container="true">[Verse 1]<br/>The brighter sky<br/>My song returns</div>'
                            '<div data-lyrics-container="true">[Chorus]<br/>Stars rise again<br/>Stars rise again</div>')
        if 'lyrics.ovh' in url:
            return Response(dict(lyrics='Different words '+('from a third site '*9)))
        raise AssertionError(url)


class YouTubeImportTest(unittest.TestCase):
    def test_video_url_rejects_playlists_and_foreign_hosts(self):
        from youtube_import import video_url

        self.assertEqual(video_url('https://youtu.be/abcdefghijk?t=10'),
                         'https://www.youtube.com/watch?v=abcdefghijk')
        for url in ('https://evil.example/watch?v=abcdefghijk',
                    'http://youtube.com/watch?v=abcdefghijk',
                    'https://youtube.com/playlist?list=abc'):
            with self.assertRaises(ValueError):
                video_url(url)

    def test_import_compares_candidates_and_saves_selected_lyrics(self):
        from youtube_import import import_youtube

        def downloader(url, folder):
            path = Path(folder)/'audio.wav'
            path.write_bytes(b'RIFF audio bytes for a mocked download')
            return path, dict(title='Sky Song', artist='Singer', duration=123)

        def request(endpoint, payload, timeout):
            self.assertEqual(len(json.loads(payload['messages'][1]['content'])['candidates']), 3)
            return dict(message=dict(content=json.dumps(dict(best_index=1, scores=[75, 96, 18],
                                                              reason='Genius matches the full song'))))

        with tempfile.TemporaryDirectory() as folder:
            result = import_youtube('https://youtu.be/abcdefghijk', Path(folder)/'library',
                                    session=Session(), request=request, model='qwen3:14b', downloader=downloader)
            self.assertTrue(Path(result['audio_path']).is_file())
            self.assertEqual(result['lyrics_source'], 'Genius')
            self.assertIn('Stars rise again', result['lyrics'])
            self.assertEqual([item['score'] for item in result['candidates']], [75, 96, 18])

    def test_rejected_lyric_candidates_leave_transcription_available(self):
        from youtube_import import choose_lyrics

        candidates = [dict(source='Genius', title='Different Song', artist='Someone',
                           lyrics='Some unrelated words repeated across an unrelated chorus')]
        request = lambda *a, **k: dict(message=dict(content=json.dumps(dict(
            best_index=0, scores=[12], reason='Wrong recording'))))
        chosen, scores = choose_lyrics(dict(title='Sky Song', artist='Singer'), candidates,
                                       request=request, model='qwen3:14b')
        self.assertIsNone(chosen)
        self.assertEqual(scores, [12])


if __name__ == '__main__':
    unittest.main()
