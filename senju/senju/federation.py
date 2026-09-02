"""Federated multi-agent action bus for Senju.

This module joins decision-producing subsystems (BOSS/R&D/Foundry/Outside World)
to Senju's bounded external HTTP transport through a declarative Action Intent.

Authority is executor-owned:
- producers cannot widen host allowlists;
- producers cannot grant themselves secret environment variables;
- producers cannot raise the allowed effect level;
- DELETE requires both max_effect=delete and allow_delete=True.

Within those boundaries, multiple producers can submit dependency-aware API steps,
chain earlier response JSON/text into later requests, and receive one auditable run
receipt with per-step external-contact evidence.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .external import (
    ContactResult,
    ExternalContactClient,
    ExternalContactError,
    ExternalContactPolicy,
)


class FederationError(RuntimeError):
    """Invalid intent or failed federated execution."""


_EFFECT_ORDER = {"read": 0, "write": 1, "delete": 2}
_READ_METHODS = {"GET", "HEAD", "OPTIONS"}
_WRITE_METHODS = {"POST", "PUT", "PATCH"}
_DELETE_METHODS = {"DELETE"}
_TEMPLATE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_SECRET_EXACT = re.compile(r"^\{\{\s*secret\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")


@dataclass(frozen=True)
class CompiledStep:
    id: str
    producer: str
    priority: int
    after: tuple[str, ...]
    method: str
    url: Any
    headers: Mapping[str, Any]
    json_body: Any
    raw_body: Any
    expect_status: Any
    continue_on_error: bool


def _documents(value: Any) -> list[dict[str, Any]]:
    """Normalize one loaded JSON value into action-intent documents."""
    if isinstance(value, list):
        docs = value
    elif isinstance(value, dict) and isinstance(value.get("intents"), list):
        docs = value["intents"]
    else:
        docs = [value]
    out: list[dict[str, Any]] = []
    for doc in docs:
        if not isinstance(doc, dict):
            raise FederationError("every action intent must be a JSON object")
        schema = doc.get("schema")
        if schema not in {None, "senju-action-intents/v1"}:
            raise FederationError(f"unsupported intent schema: {schema}")
        out.append(doc)
    return out


def load_intent_files(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise FederationError(f"intent file not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise FederationError(f"invalid JSON in intent file {path}: {exc}") from exc
        docs.extend(_documents(value))
    return docs


def _priority(value: Any, default: int = 50) -> int:
    try:
        return max(0, min(int(value if value is not None else default), 1000))
    except (TypeError, ValueError) as exc:
        raise FederationError(f"invalid priority: {value!r}") from exc


def compile_steps(documents: Sequence[dict[str, Any]], max_steps: int = 32) -> list[CompiledStep]:
    """Merge producer documents and produce a dependency-safe execution plan."""
    compiled: list[CompiledStep] = []
    seen: set[str] = set()

    for doc_index, doc in enumerate(documents):
        producer = str(doc.get("producer") or f"producer-{doc_index + 1}").strip()
        if not producer:
            raise FederationError("producer must not be empty")
        doc_priority = _priority(doc.get("priority"), 50)
        steps = doc.get("steps") or []
        if not isinstance(steps, list):
            raise FederationError(f"{producer}: steps must be a list")
        for raw in steps:
            if not isinstance(raw, dict):
                raise FederationError(f"{producer}: step must be an object")
            step_id = str(raw.get("id") or "").strip()
            if not _SAFE_ID.fullmatch(step_id):
                raise FederationError(
                    f"{producer}: invalid step id {step_id!r}; use letters/numbers/._:-"
                )
            if step_id in seen:
                raise FederationError(f"duplicate step id: {step_id}")
            seen.add(step_id)

            method = str(raw.get("method") or "GET").upper().strip()
            if method not in _READ_METHODS | _WRITE_METHODS | _DELETE_METHODS:
                raise FederationError(f"{step_id}: unsupported method {method}")

            after_raw = raw.get("after") or []
            if isinstance(after_raw, str):
                after_raw = [after_raw]
            if not isinstance(after_raw, list) or not all(
                isinstance(x, str) and x.strip() for x in after_raw
            ):
                raise FederationError(f"{step_id}: after must be a string or list of step ids")
            after = tuple(dict.fromkeys(x.strip() for x in after_raw))

            headers = raw.get("headers") or {}
            if not isinstance(headers, dict):
                raise FederationError(f"{step_id}: headers must be an object")

            if "json" in raw and "body" in raw:
                raise FederationError(f"{step_id}: choose either json or body, not both")

            compiled.append(
                CompiledStep(
                    id=step_id,
                    producer=producer,
                    priority=_priority(raw.get("priority"), doc_priority),
                    after=after,
                    method=method,
                    url=raw.get("url"),
                    headers=headers,
                    json_body=raw.get("json") if "json" in raw else None,
                    raw_body=raw.get("body") if "body" in raw else None,
                    expect_status=raw.get("expect_status"),
                    continue_on_error=bool(raw.get("continue_on_error", False)),
                )
            )

    if len(compiled) > max(1, int(max_steps)):
        raise FederationError(f"too many steps: {len(compiled)} > {max_steps}")

    ids = {s.id for s in compiled}
    for step in compiled:
        missing = [dep for dep in step.after if dep not in ids]
        if missing:
            raise FederationError(f"{step.id}: unknown dependencies: {missing}")
        if step.id in step.after:
            raise FederationError(f"{step.id}: step cannot depend on itself")

    pending = {s.id: s for s in compiled}
    completed: set[str] = set()
    plan: list[CompiledStep] = []
    while pending:
        ready = [
            s
            for s in pending.values()
            if all(dep in completed for dep in s.after)
        ]
        if not ready:
            cycle = ", ".join(sorted(pending))
            raise FederationError(f"dependency cycle detected among: {cycle}")
        ready.sort(key=lambda s: (-s.priority, s.producer, s.id))
        for step in ready:
            plan.append(step)
            completed.add(step.id)
            pending.pop(step.id)
    return plan


def _lookup(context: Mapping[str, Any], expression: str) -> Any:
    parts = [p for p in expression.strip().split(".") if p]
    if not parts:
        raise FederationError("empty template expression")
    if parts[0] == "secret":
        raise FederationError("secrets are allowed only in structured request headers")
    current: Any = context
    for part in parts:
        if isinstance(current, Mapping):
            if part not in current:
                raise FederationError(f"template value not found: {expression}")
            current = current[part]
        elif isinstance(current, (list, tuple)) and part.isdigit():
            index = int(part)
            try:
                current = current[index]
            except IndexError as exc:
                raise FederationError(f"template index out of range: {expression}") from exc
        else:
            raise FederationError(f"template path not found: {expression}")
    return current


def _render_string(value: str, context: Mapping[str, Any]) -> Any:
    exact = _TEMPLATE.fullmatch(value)
    if exact:
        return _lookup(context, exact.group(1))

    def replace(match: re.Match[str]) -> str:
        resolved = _lookup(context, match.group(1))
        if isinstance(resolved, (dict, list)):
            return json.dumps(resolved, ensure_ascii=False, separators=(",", ":"))
        return "" if resolved is None else str(resolved)

    return _TEMPLATE.sub(replace, value)


def _render_value(value: Any, context: Mapping[str, Any]) -> Any:
    if isinstance(value, str):
        return _render_string(value, context)
    if isinstance(value, list):
        return [_render_value(v, context) for v in value]
    if isinstance(value, dict):
        return {str(k): _render_value(v, context) for k, v in value.items()}
    return value


def _render_headers(
    headers: Mapping[str, Any],
    context: Mapping[str, Any],
    allowed_secret_env: set[str],
) -> dict[str, str]:
    """Render headers without ever placing secret values in the run report.

    Secret forms:
      "X-Api-Key": "{{secret.API_KEY}}"
      "Authorization": {"secret_env": "TOKEN", "prefix": "Bearer "}

    The executor must independently allow every secret name via --allow-secret-env.
    """
    rendered: dict[str, str] = {}
    for key, raw in headers.items():
        if not isinstance(key, str) or not key:
            raise FederationError("header names must be non-empty strings")

        if isinstance(raw, dict) and "secret_env" in raw:
            extra = set(raw) - {"secret_env", "prefix", "suffix"}
            if extra:
                raise FederationError(f"{key}: unsupported secret header keys: {sorted(extra)}")
            name = str(raw.get("secret_env") or "")
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise FederationError(f"{key}: invalid secret environment name")
            if name not in allowed_secret_env:
                raise FederationError(f"{key}: secret environment is not executor-allowed: {name}")
            secret = os.getenv(name, "")
            if not secret:
                raise FederationError(f"{key}: required secret environment is empty: {name}")
            prefix = str(raw.get("prefix") or "")
            suffix = str(raw.get("suffix") or "")
            if "\r" in prefix + suffix or "\n" in prefix + suffix:
                raise FederationError(f"{key}: invalid secret header prefix/suffix")
            rendered[key] = prefix + secret + suffix
            continue

        if not isinstance(raw, str):
            raise FederationError(
                f"{key}: header value must be a string or secret_env object"
            )
        match = _SECRET_EXACT.fullmatch(raw)
        if match:
            name = match.group(1)
            if name not in allowed_secret_env:
                raise FederationError(f"{key}: secret environment is not executor-allowed: {name}")
            secret = os.getenv(name, "")
            if not secret:
                raise FederationError(f"{key}: required secret environment is empty: {name}")
            rendered[key] = secret
            continue
        if "secret." in raw:
            raise FederationError(
                f"{key}: embedded secret templates are forbidden; use secret_env + prefix"
            )
        value = _render_value(raw, context)
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        rendered[key] = "" if value is None else str(value)
    return rendered


def _body_bytes(step: CompiledStep, context: Mapping[str, Any]) -> tuple[bytes | None, str | None]:
    if step.json_body is not None:
        rendered = _render_value(step.json_body, context)
        return (
            json.dumps(rendered, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            "application/json",
        )
    if step.raw_body is not None:
        rendered = _render_value(step.raw_body, context)
        if isinstance(rendered, (dict, list)):
            rendered = json.dumps(rendered, ensure_ascii=False, separators=(",", ":"))
        return str(rendered).encode("utf-8"), None
    return None, None


def _response_json(result: ContactResult) -> Any:
    if not result.body:
        return None
    try:
        return json.loads(result.body.decode("utf-8"))
    except Exception:
        return None


def _response_text(result: ContactResult, limit: int = 64 * 1024) -> str:
    if not result.body:
        return ""
    return result.body[:limit].decode("utf-8", errors="replace")


def _expect_status(spec: Any, status: int) -> bool:
    if spec is None:
        return 200 <= int(status) < 400
    if isinstance(spec, int):
        return status == spec
    if isinstance(spec, list):
        try:
            return status in {int(x) for x in spec}
        except (TypeError, ValueError) as exc:
            raise FederationError(f"invalid expect_status list: {spec!r}") from exc
    if isinstance(spec, str):
        raw = spec.strip()
        m = re.fullmatch(r"(\d{3})-(\d{3})", raw)
        if m:
            return int(m.group(1)) <= status <= int(m.group(2))
        if raw.isdigit():
            return status == int(raw)
    raise FederationError(f"invalid expect_status: {spec!r}")


def _effect_for(method: str) -> str:
    method = method.upper()
    if method in _READ_METHODS:
        return "read"
    if method in _WRITE_METHODS:
        return "write"
    if method in _DELETE_METHODS:
        return "delete"
    raise FederationError(f"unsupported method: {method}")


def _effect_allowed(effect: str, max_effect: str) -> bool:
    if max_effect not in _EFFECT_ORDER:
        raise FederationError(f"invalid max_effect: {max_effect}")
    return _EFFECT_ORDER[effect] <= _EFFECT_ORDER[max_effect]


def _safe_artifact_name(step_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", step_id)[:96]


def run_federation(
    documents: Sequence[dict[str, Any]],
    *,
    allow_hosts: Iterable[str],
    max_effect: str = "read",
    allow_delete: bool = False,
    allowed_secret_env: Iterable[str] = (),
    vars: Mapping[str, Any] | None = None,
    out_dir: str | Path = "reports/federation",
    max_steps: int = 32,
    max_total_response_bytes: int = 2 * 1024 * 1024,
    follow_redirects: bool = False,
    max_redirects: int = 3,
    timeout_seconds: float = 8.0,
    max_response_bytes: int = 512 * 1024,
    retries: int = 1,
    continue_on_error: bool = False,
    run_id: str | None = None,
    client: ExternalContactClient | None = None,
) -> dict[str, Any]:
    """Execute merged action intents through the existing guarded HTTP transport."""
    plan = compile_steps(documents, max_steps=max_steps)
    if max_effect not in _EFFECT_ORDER:
        raise FederationError(f"invalid max_effect: {max_effect}")

    policy = ExternalContactPolicy.from_hosts(
        allow_hosts,
        allow_delete=allow_delete,
        follow_redirects=follow_redirects,
        max_redirects=max_redirects,
        timeout_seconds=timeout_seconds,
        max_response_bytes=max_response_bytes,
        retries=retries,
    )
    http = client or ExternalContactClient(policy)
    secret_allow = {str(x) for x in allowed_secret_env}
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)

    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    run_id = run_id or f"fed-{uuid.uuid4().hex[:16]}"
    context: dict[str, Any] = {
        "vars": dict(vars or {}),
        "run": {"id": run_id, "started_at": started},
        "steps": {},
    }
    results: list[dict[str, Any]] = []
    total_response_bytes = 0
    success = True

    for step in plan:
        blocked_dependencies = [
            dep for dep in step.after if not bool(context["steps"].get(dep, {}).get("ok"))
        ]
        if blocked_dependencies:
            item = {
                "id": step.id,
                "producer": step.producer,
                "method": step.method,
                "effect": _effect_for(step.method),
                "ok": False,
                "skipped": True,
                "reason": "dependency_failed",
                "dependencies": list(step.after),
                "blocked_by": blocked_dependencies,
            }
            results.append(item)
            context["steps"][step.id] = dict(item)
            success = False
            if not (continue_on_error or step.continue_on_error):
                break
            continue

        effect = _effect_for(step.method)
        if not _effect_allowed(effect, max_effect):
            raise FederationError(
                f"{step.id}: effect {effect} exceeds executor max_effect={max_effect}"
            )
        if effect == "delete" and not allow_delete:
            raise FederationError(
                f"{step.id}: DELETE requires both max_effect=delete and allow_delete"
            )

        rendered_url = _render_value(step.url, context)
        if not isinstance(rendered_url, str) or not rendered_url.strip():
            raise FederationError(f"{step.id}: rendered URL must be a non-empty string")
        headers = _render_headers(step.headers, context, secret_allow)
        body, default_content_type = _body_bytes(step, context)
        if default_content_type and not any(k.lower() == "content-type" for k in headers):
            headers["Content-Type"] = default_content_type

        try:
            contact = http.contact_with_body(
                rendered_url,
                method=step.method,
                body=body,
                headers=headers,
            )
            receipt = contact.receipt.to_dict()
            body_path = output / f"{_safe_artifact_name(step.id)}.response.bin"
            receipt_path = output / f"{_safe_artifact_name(step.id)}.receipt.json"
            contact.write_body(body_path)
            contact.receipt.write(receipt_path)

            total_response_bytes += len(contact.body)
            if total_response_bytes > max(1024, int(max_total_response_bytes)):
                raise FederationError(
                    f"federation response budget exceeded: "
                    f"{total_response_bytes} > {max_total_response_bytes}"
                )

            status = int(receipt["status"])
            ok = _expect_status(step.expect_status, status)
            parsed = _response_json(contact)
            text = _response_text(contact)
            item = {
                "id": step.id,
                "producer": step.producer,
                "priority": step.priority,
                "dependencies": list(step.after),
                "method": step.method,
                "effect": effect,
                "ok": ok,
                "status": status,
                "requested_url": receipt["requested_url"],
                "final_url": receipt["final_url"],
                "response_bytes": len(contact.body),
                "response_sha256": receipt["response_sha256"],
                "receipt_schema": receipt["schema"],
                "response_json": parsed,
                "response_text_preview": text[:1000],
                "artifact_response": str(body_path),
                "artifact_receipt": str(receipt_path),
            }
            results.append(item)
            context["steps"][step.id] = {
                "ok": ok,
                "producer": step.producer,
                "effect": effect,
                "status": status,
                "url": receipt["final_url"],
                "json": parsed,
                "text": text,
                "receipt": receipt,
            }
            if not ok:
                success = False
                if not (continue_on_error or step.continue_on_error):
                    break
        except (ExternalContactError, FederationError) as exc:
            item = {
                "id": step.id,
                "producer": step.producer,
                "priority": step.priority,
                "dependencies": list(step.after),
                "method": step.method,
                "effect": effect,
                "ok": False,
                "error": type(exc).__name__,
                "message": str(exc)[:1000],
            }
            results.append(item)
            context["steps"][step.id] = dict(item)
            success = False
            if not (continue_on_error or step.continue_on_error):
                break

    finished = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    report = {
        "schema": "senju-federation-run/v1",
        "run_id": run_id,
        "started_at_utc": started,
        "finished_at_utc": finished,
        "success": success and len(results) == len(plan) and all(
            bool(x.get("ok")) for x in results
        ),
        "max_effect": max_effect,
        "allow_delete": bool(allow_delete),
        "producers": sorted({s.producer for s in plan}),
        "planned_steps": len(plan),
        "executed_steps": len(results),
        "total_response_bytes": total_response_bytes,
        "steps": results,
    }
    (output / "federation-run.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def _parse_vars(values: Iterable[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in values:
        if "=" not in raw:
            raise FederationError(f"--var must be KEY=VALUE: {raw!r}")
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise FederationError("--var key must not be empty")
        out[key] = value
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Execute multi-producer Senju Action Intents through guarded HTTP"
    )
    p.add_argument("--intent", action="append", required=True)
    p.add_argument("--allow-host", action="append", default=[])
    p.add_argument("--var", action="append", default=[])
    p.add_argument("--max-effect", choices=["read", "write", "delete"], default="read")
    p.add_argument("--allow-delete", action="store_true")
    p.add_argument("--allow-secret-env", action="append", default=[])
    p.add_argument("--follow-redirects", action="store_true")
    p.add_argument("--max-redirects", type=int, default=3)
    p.add_argument("--timeout", type=float, default=8.0)
    p.add_argument("--retries", type=int, default=1)
    p.add_argument("--max-steps", type=int, default=32)
    p.add_argument("--max-total-response-bytes", type=int, default=2 * 1024 * 1024)
    p.add_argument("--out-dir", default="reports/federation")
    p.add_argument("--continue-on-error", action="store_true")
    args = p.parse_args(argv)

    docs = load_intent_files(args.intent)
    report = run_federation(
        docs,
        allow_hosts=args.allow_host,
        max_effect=args.max_effect,
        allow_delete=args.allow_delete,
        allowed_secret_env=args.allow_secret_env,
        vars=_parse_vars(args.var),
        out_dir=args.out_dir,
        max_steps=args.max_steps,
        max_total_response_bytes=args.max_total_response_bytes,
        follow_redirects=args.follow_redirects,
        max_redirects=args.max_redirects,
        timeout_seconds=args.timeout,
        retries=args.retries,
        continue_on_error=args.continue_on_error,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
