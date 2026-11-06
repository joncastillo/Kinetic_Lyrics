"""Exercise commit copying against real, disposable Git repositories."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'automation' / 'copy_commits.py'


class CopyCommitsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='test-copy-commits-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.target = self.root / 'target'
        self.env = {
            **os.environ,
            'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_GLOBAL': os.devnull,
            'GIT_TERMINAL_PROMPT': '0',
        }
        self.git(self.root, 'init', '--quiet', '--initial-branch=main', str(self.source))
        self.identity(self.source, 'Source User', 'source@example.test')
        self.commit(self.source, 'Initial files', {'shared.txt': 'base\n'})
        self.git(self.root, 'clone', '--quiet', str(self.source), str(self.target))
        self.identity(self.target, 'Target User', 'target@example.test')
        self.base = self.git(self.source, 'rev-parse', 'HEAD')

    def git(self, repo, *args):
        return subprocess.run(
            ['git', *args],
            cwd=repo,
            env=self.env,
            check=True,
            capture_output=True,
            encoding='utf-8',
            errors='replace',
        ).stdout.strip()

    def identity(self, repo, name, email):
        self.git(repo, 'config', 'user.name', name)
        self.git(repo, 'config', 'user.email', email)

    def commit(self, repo, message, files):
        for name, content in files.items():
            (repo / name).write_text(content, encoding='utf-8')
        self.git(repo, 'add', '.')
        self.git(repo, 'commit', '--quiet', '-m', message)
        return self.git(repo, 'rev-parse', 'HEAD')

    def script(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(self.source), *args],
            cwd=self.target,
            env=self.env,
            capture_output=True,
            encoding='utf-8',
            errors='replace',
        )

    def assert_untouched(self, head, status=''):
        self.assertEqual(self.git(self.target, 'rev-parse', 'HEAD'), head)
        self.assertEqual(self.git(self.target, 'status', '--porcelain'), status)
        self.assertFalse((self.target / '.git' / 'CHERRY_PICK_HEAD').exists())

    def test_copy_preserves_local_changes_and_uses_local_identity(self):
        self.commit(self.target, 'Local feature', {'local.txt': 'keep me\n'})
        source_tip = self.commit(
            self.source,
            'New feature\n\n1. Add the feature\n\nCo-Authored-By: Someone <someone@example.test>',
            {'new.txt': 'new feature\n'},
        )
        result = self.script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.target / 'new.txt').read_text(), 'new feature\n')
        self.assertEqual((self.target / 'local.txt').read_text(), 'keep me\n')
        self.assertEqual(self.git(self.target, 'log', '-1', '--format=%an <%ae>'), 'Target User <target@example.test>')
        self.assertNotIn('Co-Authored-By', self.git(self.target, 'log', '-1', '--format=%B'))
        self.assertEqual(self.git(self.source, 'rev-parse', 'HEAD'), source_tip)
        self.assertEqual(self.git(self.source, 'status', '--porcelain'), '')
        # The copied patch must be recognised on a repeat run.
        head = self.git(self.target, 'rev-parse', 'HEAD')
        repeat = self.script()
        self.assertEqual(repeat.returncode, 0, repeat.stdout + repeat.stderr)
        self.assertIn('Nothing to copy', repeat.stdout)
        self.assert_untouched(head)

    def test_dry_run_checks_whole_sequence_without_applying_it(self):
        self.commit(self.source, 'First change', {'first.txt': 'first\n'})
        self.commit(self.source, 'Second change', {'second.txt': 'second\n'})
        (self.target / 'notes.txt').write_text('untracked notes\n', encoding='utf-8')
        before = self.git(self.target, 'status', '--porcelain')
        result = self.script('--dry-run')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Would copy 2', result.stdout)
        self.assertIn('Conflict check passed', result.stdout)
        self.assert_untouched(self.base, before)
        self.assertFalse((self.target / 'first.txt').exists())

    def test_later_conflict_leaves_no_partial_copy_in_either_mode(self):
        head = self.commit(self.target, 'Local edit', {'shared.txt': 'local version\n'})
        self.commit(self.source, 'Clean first change', {'new.txt': 'new\n'})
        self.commit(self.source, 'Conflicting second change', {'shared.txt': 'source version\n'})
        for args in ((), ('--dry-run',)):
            with self.subTest(args=args):
                result = self.script(*args)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn('Conflicting second change', result.stderr)
                self.assertIn('shared.txt', result.stderr)
                self.assert_untouched(head)
                self.assertFalse((self.target / 'new.txt').exists())

    def test_since_handles_changes_integrated_in_a_larger_commit(self):
        integrated = self.commit(self.source, 'Upstream edit', {'shared.txt': 'upstream\n'})
        head = self.commit(self.target, 'Combined edit', {'shared.txt': 'upstream\nlocal addition\n'})
        self.commit(self.source, 'New change', {'new.txt': 'new\n'})
        # Patch IDs cannot match the older combined edit. Preflight catches its replay.
        refused = self.script()
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertIn('--since', refused.stderr)
        self.assert_untouched(head)
        result = self.script('--since', integrated)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.target / 'shared.txt').read_text(), 'upstream\nlocal addition\n')
        self.assertEqual((self.target / 'new.txt').read_text(), 'new\n')

    def test_reverse_patch_recognises_latest_change_in_a_combined_commit(self):
        self.commit(self.source, 'Intermediate edit', {'shared.txt': 'intermediate\n'})
        self.commit(self.source, 'Final edit', {'shared.txt': 'final\n'})
        head = self.commit(
            self.target,
            'Combined edit and local feature',
            {
                'shared.txt': 'final\n',
                'local.txt': 'local feature\n',
            },
        )
        result = self.script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Nothing to copy', result.stdout)
        self.assert_untouched(head)

    def test_reverse_patch_requires_every_file_to_be_present(self):
        self.commit(self.source, 'Two files', {'first.txt': 'first\n', 'second.txt': 'second\n'})
        self.commit(self.target, 'Only one file copied', {'first.txt': 'first\n'})
        result = self.script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.target / 'second.txt').read_text(), 'second\n')

    def test_untracked_collision_leaves_no_partial_copy(self):
        self.commit(self.source, 'Clean first change', {'first.txt': 'first\n'})
        self.commit(self.source, 'Later collision', {'notes.txt': 'source notes\n'})
        (self.target / 'notes.txt').write_text('my notes\n', encoding='utf-8')
        before = self.git(self.target, 'status', '--porcelain')
        result = self.script()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('untracked', result.stderr)
        self.assert_untouched(self.base, before)
        self.assertEqual((self.target / 'notes.txt').read_text(), 'my notes\n')
        self.assertFalse((self.target / 'first.txt').exists())

    def test_explicit_range_does_not_stop_at_a_newer_patch_match(self):
        self.commit(self.source, 'Missing older change', {'missing.txt': 'needed\n'})
        known = self.commit(self.source, 'Already copied', {'known.txt': 'known\n'})
        self.git(self.target, 'fetch', '--quiet', str(self.source), 'HEAD')
        self.git(self.target, 'cherry-pick', known)
        self.commit(self.source, 'Newest change', {'new.txt': 'new\n'})
        result = self.script('--since', self.base)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.target / 'missing.txt').read_text(), 'needed\n')
        self.assertEqual(self.git(self.target, 'rev-list', '--count', 'HEAD'), '4')

    def test_since_must_be_in_the_source_history(self):
        head = self.commit(self.target, 'Target only', {'local.txt': 'local\n'})
        self.commit(self.source, 'Source only', {'new.txt': 'new\n'})
        result = self.script('--since', head)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('source branch', result.stderr)
        self.assert_untouched(head)

    def test_resolved_import_boundary_does_not_replay_merged_changes(self):
        integrated = self.commit(self.source, 'Incoming change', {'shared.txt': 'incoming\n'})
        self.commit(self.target, 'Resolved import\n\n1. Preserve both features.\n\n'
                    f'Integrated-source-commit: {integrated}', {'shared.txt': 'incoming with local changes\n'})
        self.commit(self.source, 'Next change', {'next.txt': 'next\n'})
        result = self.script()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual((self.target/'shared.txt').read_text(), 'incoming with local changes\n')
        self.assertEqual((self.target/'next.txt').read_text(), 'next\n')
        repeat = self.script()
        self.assertEqual(repeat.returncode, 0, repeat.stdout+repeat.stderr)
        self.assertIn('Nothing to copy', repeat.stdout)

    def test_integration_marker_from_another_source_is_ignored(self):
        other = self.commit(self.target, 'Target change', {'local.txt': 'local\n'})
        self.commit(self.target, f'Unrelated marker\n\nIntegrated-source-commit: {other}', {'extra.txt': 'extra\n'})
        self.commit(self.source, 'Source change', {'new.txt': 'new\n'})
        result = self.script()
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual((self.target/'new.txt').read_text(), 'new\n')

    def test_empty_cherry_pick_in_progress_is_refused(self):
        commit = self.commit(self.source, 'Source change', {'new.txt': 'new\n'})
        self.git(self.target, 'fetch', '--quiet', str(self.source), 'HEAD')
        self.git(self.target, 'cherry-pick', commit)
        head = self.git(self.target, 'rev-parse', 'HEAD')
        subprocess.run(['git', 'cherry-pick', commit], cwd=self.target, env=self.env, capture_output=True)
        self.assertTrue((self.target / '.git' / 'CHERRY_PICK_HEAD').exists())
        result = self.script()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('already in progress', result.stderr)
        self.assertEqual(self.git(self.target, 'rev-parse', 'HEAD'), head)
        self.assertTrue((self.target / '.git' / 'CHERRY_PICK_HEAD').exists())

    def test_private_source_is_refused_before_fetch_into_public(self):
        private = self.commit(self.source, 'Private extension', {'.private-repository': 'private\n', 'private.txt': 'private\n'})
        before = self.git(self.target, 'rev-parse', 'HEAD')
        result = self.script()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('nothing was fetched', result.stderr)
        self.assert_untouched(before)
        probe = subprocess.run(['git', 'cat-file', '-e', private], cwd=self.target, env=self.env, capture_output=True)
        self.assertNotEqual(probe.returncode, 0)

    def test_public_updates_import_with_private_marker_and_keep_private_files(self):
        self.commit(self.target, 'Private extensions', {'.private-repository': 'private\n', 'private.txt': 'keep\n'})
        self.commit(self.source, 'Shared update', {'shared.txt':'updated\n'})
        result = self.script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.target/'shared.txt').read_text(), 'updated\n')
        self.assertEqual((self.target/'private.txt').read_text(), 'keep\n')
        self.assertTrue((self.target/'.private-repository').exists())


if __name__ == '__main__':
    unittest.main()
