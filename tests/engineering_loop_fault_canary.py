from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / 'automation' / 'ai_foundry' / 'engineering_loop.py'
spec = importlib.util.spec_from_file_location('engineering_loop_v2_fault_canary', MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)

original_write_files = mod.write_files
state = {'writes': 0, 'fault_injected': False}


def write_files_with_one_fault(root: Path, files: list[dict[str, str]]) -> None:
    original_write_files(root, files)
    if state['writes'] == 0:
        for item in files:
            if item['path'].endswith('.js'):
                target = root / item['path']
                target.write_text(target.read_text(encoding='utf-8') + '\nconst = ; // AI_FOUNDRY_FORCED_CANARY_FAULT\n', encoding='utf-8')
                state['fault_injected'] = True
                break
    state['writes'] += 1


mod.write_files = write_files_with_one_fault

if __name__ == '__main__':
    code = mod.main()
    if not state['fault_injected']:
        raise SystemExit('fault canary could not find a generated JavaScript file')
    raise SystemExit(code)
