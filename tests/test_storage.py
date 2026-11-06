"""Where projects are kept, and the song kept in a project under its own name."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from core import paths
from studio import server


class ProjectsFolderTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.settings = self.home/'settings.json'
        self.install = self.home/'install'/'app'
        self.install.mkdir(parents=True)
        self.patches = [mock.patch.object(paths, 'SETTINGS', self.settings),
                        mock.patch.object(paths, 'documents_folder', return_value=self.home/'Documents'),
                        mock.patch.dict(os.environ)]
        for patch in self.patches:
            patch.start()
        os.environ.pop('KINETIC_LYRICS_OUTPUT', None)
        self.addCleanup(lambda: [patch.stop() for patch in self.patches])

    def folder(self):
        return paths.studio_output(self.install)

    def test_a_new_install_keeps_projects_in_documents(self):
        self.assertEqual(self.folder(), self.home/'Documents'/'Kinetic Lyrics')

    def test_an_install_with_projects_keeps_finding_them(self):
        old = self.install/'output'/'lyric-studio'
        old.mkdir(parents=True)
        self.assertEqual(self.folder(), old)

    def test_the_saved_folder_wins_and_clearing_it_goes_back(self):
        (self.install/'output'/'lyric-studio').mkdir(parents=True)
        chosen = self.home/'Songs'
        paths.save_projects_folder(str(chosen))
        self.assertEqual(self.folder(), chosen.resolve())
        self.assertTrue(chosen.is_dir(), 'made when saved, so a bad path is found out now')
        paths.save_projects_folder('')
        self.assertEqual(self.folder(), self.install/'output'/'lyric-studio')

    def test_the_environment_wins_over_everything(self):
        paths.save_projects_folder(str(self.home/'Songs'))
        os.environ['KINETIC_LYRICS_OUTPUT'] = str(self.home/'Env')
        self.assertEqual(self.folder(), (self.home/'Env').resolve())

    def test_a_folder_that_cannot_be_used_is_refused_and_not_saved(self):
        with self.assertRaises(ValueError):
            paths.save_projects_folder('relative/folder')
        blocked = self.home/'file'
        blocked.write_text('x')
        with self.assertRaises(ValueError):
            paths.save_projects_folder(str(blocked/'inside'))
        self.assertFalse(self.settings.exists())

    def test_a_broken_settings_file_is_ignored(self):
        self.settings.write_text('not json')
        self.assertEqual(self.folder(), self.home/'Documents'/'Kinetic Lyrics')


class AudioNameTest(unittest.TestCase):
    def test_the_song_keeps_its_name(self):
        self.assertEqual(server.audio_file_name('My Song (Live) - Take 2.mp3'), 'My Song (Live) - Take 2.mp3')
        self.assertEqual(server.audio_file_name('Sa pader ng istasyon.flac'), 'Sa pader ng istasyon.flac')

    def test_no_folders_or_characters_windows_refuses_get_through(self):
        self.assertEqual(server.audio_file_name('../../evil.mp3'), 'evil.mp3')
        self.assertEqual(server.audio_file_name('C:\\Music\\song.mp3'), 'song.mp3')
        self.assertEqual(server.audio_file_name('what? a: "song".mp3'), 'what_ a_ _song_.mp3')

    def test_a_name_the_project_uses_itself_is_set_apart(self):
        for name in ('video.mp4', 'VOCALS.wav', 'con.mp3'):
            self.assertEqual(server.audio_file_name(name), 'song-'+name, name)

    def test_a_name_with_nothing_left_falls_back(self):
        self.assertEqual(server.audio_file_name('.mp3'), 'audio.mp3')


class ProjectAudioTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())

    def test_a_new_song_is_saved_under_its_own_name(self):
        path, replaced = server.save_audio(self.folder, 'My Song.mp3', b'tune')
        self.assertEqual((path.name, replaced), ('My Song.mp3', False))
        self.assertEqual(path.read_bytes(), b'tune')

    def test_an_older_project_keeps_its_audio_file_on_a_restart(self):
        (self.folder/'audio.mp3').write_bytes(b'tune')
        path, replaced = server.save_audio(self.folder, 'My Song.mp3', b'tune')
        self.assertEqual((path.name, replaced), ('audio.mp3', False))

    def test_a_different_song_replaces_the_old_one_under_its_own_name(self):
        (self.folder/'config.json').write_text(json.dumps(dict(audio=str(self.folder/'Old.mp3'))), encoding='utf-8')
        (self.folder/'Old.mp3').write_bytes(b'old')
        with mock.patch.object(server, 'forget_audio_analysis') as forget:
            path, replaced = server.save_audio(self.folder, 'New.wav', b'new')
        self.assertEqual((path.name, replaced), ('New.wav', True))
        self.assertFalse((self.folder/'Old.mp3').exists())
        forget.assert_called_once()

    def test_the_song_is_found_by_its_record_or_the_old_name(self):
        self.assertEqual(server.project_audio(self.folder), [])
        (self.folder/'audio.mp3').write_bytes(b'x')
        self.assertEqual([p.name for p in server.project_audio(self.folder)], ['audio.mp3'])
        (self.folder/'audio.mp3').unlink()
        (self.folder/'Song.flac').write_bytes(b'x')
        (self.folder/'config.json').write_text(json.dumps(dict(audio='D:/moved/from/here/Song.flac')), encoding='utf-8')
        self.assertEqual([p.name for p in server.project_audio(self.folder)], ['Song.flac'], 'a project moved on disk too')

    def test_the_output_video_is_never_taken_for_the_song(self):
        (self.folder/'video.mp4').write_bytes(b'x')
        self.assertEqual(server.project_audio(self.folder), [])


if __name__ == '__main__':
    unittest.main()
