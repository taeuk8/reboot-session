import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from reboot_session.core import (atomic_write, fingerprint, item, plan, read_json,
                                 RestoreEngine, validate, validate_task)
from reboot_session.windows import terminal_args, wez_cwd


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.row = item('folder', '작업', {'path': 'C:\\한글 폴더'})

    def test_atomic_roundtrip_unicode(self):
        saved = plan([self.row])
        atomic_write(self.root / 'nested' / 'plan.json', saved)
        self.assertEqual(validate(read_json(self.root / 'nested' / 'plan.json')), saved)

    def test_failed_replace_preserves_previous_plan(self):
        path = self.root / 'plan.json'
        atomic_write(path, {'old': True})
        with patch('reboot_session.core.os.replace', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                atomic_write(path, {'new': True})
        self.assertEqual(read_json(path), {'old': True})
        self.assertEqual(list(self.root.iterdir()), [path])

    def test_unknown_version_and_duplicate_ids_rejected(self):
        for saved in [dict(plan([self.row]), version=999), plan([self.row, self.row])]:
            with self.assertRaises(ValueError):
                validate(saved)

    def test_plan_path_traversal_rejected(self):
        saved = plan([self.row])
        saved['id'] = '../../secret'
        with self.assertRaises(ValueError):
            validate(saved)

    def test_work_change_detected_but_selection_ignored(self):
        before = fingerprint([self.row])
        self.row['selected'] = False
        self.assertEqual(before, fingerprint([self.row]))
        self.row['payload']['path'] = 'D:\\other'
        self.assertNotEqual(before, fingerprint([self.row]))

    def test_success_not_repeated_even_on_retry(self):
        calls = []
        engine = RestoreEngine(self.root, lambda r: calls.append(r['id']) or 'ok')
        saved = plan([self.row])
        engine.run(saved)
        engine.run(saved)
        engine.run(saved, retry=True)
        self.assertEqual(calls, [self.row['id']])

    def test_failure_isolated_and_retried_only_explicitly(self):
        other = item('folder', 'other', {'path': 'D:\\other'})
        calls = []
        def launch(row):
            calls.append(row['id'])
            if row['id'] == self.row['id']:
                raise FileNotFoundError('missing')
            return 'ok'
        engine = RestoreEngine(self.root, launch)
        saved = plan([self.row, other])
        result = engine.run(saved)
        self.assertEqual(result['items'][self.row['id']]['state'], 'failed')
        self.assertEqual(result['items'][other['id']]['state'], 'launched')
        engine.run(saved)
        self.assertEqual(len(calls), 2)
        engine.run(saved, retry=True)
        self.assertEqual(len(calls), 3)

    def test_interrupted_launch_not_automatically_repeated(self):
        saved = plan([self.row])
        atomic_write(self.root / ('result-' + saved['id'] + '.json'),
                     {'plan_id': saved['id'], 'items': {self.row['id']: {'state': 'launching'}}})
        calls = []
        engine = RestoreEngine(self.root, lambda r: calls.append(r) or 'ok')
        engine.run(saved)
        self.assertEqual(calls, [])
        engine.run(saved, retry=True)
        self.assertEqual(len(calls), 1)

    def test_result_write_failure_prevents_launch(self):
        calls = []
        with patch('reboot_session.core.atomic_write', side_effect=OSError('full')):
            with self.assertRaises(OSError):
                RestoreEngine(self.root, lambda r: calls.append(r)).run(plan([self.row]))
        self.assertEqual(calls, [])

    def test_unselected_never_executed(self):
        self.row['selected'] = False
        calls = []
        RestoreEngine(self.root, lambda r: calls.append(r)).run(plan([self.row]))
        self.assertEqual(calls, [])


class TerminalTests(unittest.TestCase):
    def test_ai_tasks_require_specific_session(self):
        for tool in ('codex', 'opencode'):
            with self.assertRaises(ValueError):
                validate_task({'name': 'a', 'cwd': 'C:\\x', 'tool': tool})

    def test_wsl_argv_keeps_paths_and_session_separate(self):
        task = {'name': 'a', 'cwd': '/home/me/my project', 'tool': 'codex',
                'session': 'session-123', 'environment': 'wsl', 'distro': 'Ubuntu'}
        self.assertEqual(terminal_args(task), ['wsl.exe', '--distribution', 'Ubuntu', '--cd',
                                             '/home/me/my project', '--exec', 'codex', 'resume', 'session-123'])

    def test_windows_session_shell_characters_are_literal(self):
        import base64
        task = {'name': 'a', 'cwd': 'C:\\x', 'tool': 'codex', 'session': "abc'; Remove-Item x; '"}
        args = terminal_args(task)
        script = base64.b64decode(args[-1]).decode('utf-16le')
        self.assertEqual(script, "& 'codex' 'resume' 'abc''; Remove-Item x; '''")

    def test_only_registered_command_is_reexecuted(self):
        task = {'name': 'server', 'cwd': 'C:\\x', 'tool': 'command', 'command': 'npm run dev'}
        self.assertEqual(terminal_args(task), ['powershell.exe', '-NoExit', '-Command', 'npm run dev'])

    def test_windows_file_uri_decodes_and_remote_path_requires_registration(self):
        self.assertEqual(wez_cwd('file://host/C:/my%20project'), 'C:/my project')
        self.assertEqual(wez_cwd('file://linux/home/me'), '')
        self.assertEqual(wez_cwd(''), '')


class StartupTests(unittest.TestCase):
    def test_arm_verify_and_disarm_without_restarting(self):
        import reboot_session.windows as win
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            startup = root / 'Startup' / 'RebootSession.cmd'
            saved = plan([])
            with patch.object(win, 'require_windows'), patch.object(win, 'startup_path', return_value=startup), \
                 patch.object(win, 'launch_command', return_value=['C:\\한글&폴더\\app.exe', '--restore', saved['id']]), \
                 patch.object(win, 'boot_id', return_value='boot-1'):
                win.arm(root, saved)
                self.assertEqual(read_json(root / 'pending.json')['plan_id'], saved['id'])
                self.assertIn(b'chcp 65001', startup.read_bytes())
                self.assertIn('"C:\\한글&폴더\\app.exe"'.encode('utf-8'), startup.read_bytes())
                self.assertIn(b'DisableDelayedExpansion', startup.read_bytes())
                self.assertNotIn(b'\r\r\n', startup.read_bytes())
                win.disarm(root)
                self.assertFalse(startup.exists())
                self.assertFalse((root / 'pending.json').exists())

    def test_startup_write_failure_cleans_pending(self):
        import reboot_session.windows as win
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            startup = root / 'Startup' / 'RebootSession.cmd'
            with patch.object(win, 'require_windows'), patch.object(win, 'startup_path', return_value=startup), \
                 patch.object(win, 'boot_id', return_value='boot-1'), \
                 patch.object(win, 'launch_command', return_value=['C:\\app.exe']), \
                 patch.object(Path, 'write_bytes', side_effect=OSError('denied')):
                with self.assertRaises(OSError):
                    win.arm(root, plan([]))
                self.assertFalse((root / 'pending.json').exists())

    def test_restart_never_forces_application_shutdown(self):
        import reboot_session.windows as win
        with patch.object(win, 'require_windows'), patch.object(win.subprocess, 'run') as run:
            win.request_restart()
            self.assertEqual(run.call_args.args[0], ['shutdown.exe', '/r', '/t', '0'])
            self.assertNotIn('/f', run.call_args.args[0])

    def test_non_windows_execution_is_blocked(self):
        import reboot_session.windows as win
        with patch.object(win, 'IS_WINDOWS', False):
            with self.assertRaises(RuntimeError):
                win.launch(item('folder', 'a', {'path': '/tmp'}))


if __name__ == '__main__':
    unittest.main()
