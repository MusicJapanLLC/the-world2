from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / 'automation' / 'ai_foundry' / 'engineering_loop.py'
spec = importlib.util.spec_from_file_location('engineering_loop_v2', MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


class EngineeringLoopV2Tests(unittest.TestCase):
    def test_extract_json_accepts_fenced_object(self):
        data = mod.extract_json('```json\n{"name":"x","files":[]}\n```')
        self.assertEqual(data['name'], 'x')

    def test_safe_relpath_rejects_escape(self):
        with self.assertRaises(ValueError): mod.safe_relpath('../outside.txt')
        with self.assertRaises(ValueError): mod.safe_relpath('/absolute.txt')
        with self.assertRaises(ValueError): mod.safe_relpath('.git/config')

    def test_safe_relpath_accepts_nested_project_file(self):
        self.assertEqual(mod.safe_relpath('src/app.js'), 'src/app.js')

    def test_command_policy_allows_local_validation(self):
        self.assertEqual(mod.validate_command('node --check app.js'), 'node --check app.js')
        self.assertEqual(mod.validate_command('python -m unittest'), 'python -m unittest')

    def test_command_policy_blocks_shell_and_publish(self):
        for command in ('node --check app.js && echo pwn','python test.py > out.txt','npm publish','npx vercel deploy'):
            with self.subTest(command=command):
                with self.assertRaises(ValueError): mod.validate_command(command)

    def test_normalize_files_blocks_duplicate(self):
        with self.assertRaises(ValueError):
            mod.normalize_files([{'path':'a.txt','content':'1'},{'path':'a.txt','content':'2'}])

    def test_scrubbed_env_removes_common_secret_names(self):
        old = dict(os.environ)
        try:
            os.environ['GITHUB_TOKEN']='secret'; os.environ['OPENAI_API_KEY']='secret'; os.environ['NORMAL_VALUE']='ok'
            env=mod.scrubbed_env()
            self.assertNotIn('GITHUB_TOKEN',env); self.assertNotIn('OPENAI_API_KEY',env); self.assertEqual(env.get('NORMAL_VALUE'),'ok')
        finally:
            os.environ.clear(); os.environ.update(old)

    def test_verify_requires_real_command_and_smoke_success(self):
        self.assertTrue(mod.verify([{'exit_code':0}], {'passed':True}))
        self.assertFalse(mod.verify([], {'passed':True}))
        self.assertFalse(mod.verify([{'exit_code':1}], {'passed':True}))
        self.assertFalse(mod.verify([{'exit_code':0}], {'passed':False}))


if __name__ == '__main__':
    unittest.main()
