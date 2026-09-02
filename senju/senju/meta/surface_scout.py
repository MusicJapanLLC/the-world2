"""Surface Scout — auto-discovers new attack surfaces from codebase.

No predefined list. Scans dynamically. Feeds discoveries to KnowledgeGraph.
"""
from __future__ import annotations

import json
import re
import datetime as dt
from pathlib import Path
from typing import Generator

ROOT = Path(__file__).resolve().parents[4]
STATE_DIR = ROOT / "senju" / "state"
SCOUT_LOG = STATE_DIR / "surface_scout.ndjson"

SURFACE_PATTERNS = [
    (r"def\s+(\w+).*?password", "auth_function"),
    (r"def\s+(\w+).*?token", "token_handler"),
    (r"subprocess\.\w+", "shell_exec"),
    (r"eval\s*\(", "eval_surface"),
    (r"exec\s*\(", "exec_surface"),
    (r"pickle\.loads?", "deserialization"),
    (r"yaml\.load\b", "yaml_unsafe"),
    (r"json\.loads?", "json_parse"),
    (r"requests?\.\w+", "http_client"),
    (r"open\s*\(", "file_io"),
    (r"os\.environ", "env_access"),
    (r"sqlite3|psycopg2|pymysql", "database"),
    (r"import\s+ctypes", "native_code"),
    (r"@app\.route|@router\.\w+", "web_endpoint"),
    (r"class\s+\w*(Auth|Login|Session|Token)", "auth_class"),
    (r"SECRET|PASSWORD|API_KEY|TOKEN", "secret_ref"),
    (r"threading\.|multiprocessing\.", "concurrency"),
    (r"\.format\(|f\"", "string_format"),
    (r"urllib|httplib|http\.client", "http_raw"),
    (r"socket\.\w+", "raw_socket"),
]


def _ts() -> str:
    return dt.datetime.utcnow().isoformat() + "Z"


def _log(event: str, data: dict) -> None:
    SCOUT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with SCOUT_LOG.open("a") as f:
        f.write(json.dumps({"ts": _ts(), "event": event, **data}, ensure_ascii=False) + "\n")


def scan_codebase(root: Path = ROOT, extensions: tuple = (".py", ".js", ".ts", ".go")) -> dict[str, float]:
    """Scan repo for attack surfaces. Returns {surface_name: score}."""
    surface_hits: dict[str, int] = {}
    scanned = 0
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv"}

    for path in _walk(root, extensions, skip_dirs):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            scanned += 1
            for pattern, surface_name in SURFACE_PATTERNS:
                hits = len(re.findall(pattern, text, re.IGNORECASE))
                if hits:
                    key = f"auto:{surface_name}:{path.stem}"
                    surface_hits[key] = surface_hits.get(key, 0) + hits
        except Exception:
            pass

    scores = {k: min(v * 0.1, 999.0) for k, v in surface_hits.items()}
    _log("scan", {"files_scanned": scanned, "surfaces_found": len(scores)})
    return scores


def _walk(root: Path, extensions: tuple, skip_dirs: set) -> Generator[Path, None, None]:
    for p in root.rglob("*"):
        if any(part in skip_dirs for part in p.parts):
            continue
        if p.is_file() and p.suffix in extensions:
            yield p


def inject_into_graph(graph, scores: dict[str, float]) -> int:
    """Inject discovered surfaces into KnowledgeGraph. No cap on score."""
    injected = 0
    for surface, score in scores.items():
        if surface not in graph.surface_weakness_scores:
            graph.surface_weakness_scores[surface] = score
            injected += 1
        else:
            graph.surface_weakness_scores[surface] += score * 0.5
    if injected:
        _log("inject", {"new_surfaces": injected})
    return injected
