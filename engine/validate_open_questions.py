#!/usr/bin/env python3
"""Validate an open-questions.json against the schema + status/resolution invariants.

Stdlib-only (checks are hand-coded; engine/schemas/open-questions.schema.json stays the
documentation of record). Usage: python3 engine/validate_open_questions.py <path>.
Exit 0 = OK; exit 1 = FAIL (reason on stderr). Importable: validate(doc) -> error or None.
"""
import json
import sys
from pathlib import Path

# Which resolution.kind values each status permits. `open` requires resolution null.
ALLOWED_KINDS = {
    "resolved": {"picked", "other", "you-decide"},
    "folded": {"picked", "other", "you-decide"},
    "deferred": {"skip"},
}
STATUSES = ("open", "resolved", "deferred", "folded")
KINDS = ("picked", "other", "you-decide", "skip")


def validate(doc):
    """Return an error string, or None if the document is valid."""
    if not isinstance(doc, dict):
        return "document must be an object"
    extra = set(doc) - {"schema_version", "feature_slug", "questions"}
    if extra:
        return f"unknown key(s): {', '.join(sorted(extra))}"
    if doc.get("schema_version") != 1:
        return "schema_version must be 1"
    if not isinstance(doc.get("feature_slug"), str) or not doc["feature_slug"]:
        return "feature_slug must be a non-empty string"
    questions = doc.get("questions")
    if not isinstance(questions, list):
        return "questions must be a list"

    ids = []
    for i, q in enumerate(questions):
        where = f"questions[{i}]"
        if not isinstance(q, dict):
            return f"{where} must be an object"
        extra = set(q) - {"id", "question", "why", "options", "status", "resolution"}
        if extra:
            return f"{where}: unknown key(s): {', '.join(sorted(extra))}"
        for key in ("id", "question", "why"):
            if not isinstance(q.get(key), str) or not q[key]:
                return f"{where}: {key} must be a non-empty string"
        opts = q.get("options")
        if (
            not isinstance(opts, list)
            or not (2 <= len(opts) <= 4)
            or not all(isinstance(o, str) and o for o in opts)
        ):
            return f"{where}: options must be 2-4 non-empty strings"
        if q.get("status") not in STATUSES:
            return f"{where}: bad status {q.get('status')!r}"
        res = q.get("resolution") if "resolution" in q else "MISSING"
        if res == "MISSING":
            return f"{where}: resolution key is required (may be null)"
        if res is not None:
            if not isinstance(res, dict) or set(res) != {"kind", "answer"}:
                return f"{where}: resolution must be null or {{kind, answer}}"
            if res["kind"] not in KINDS:
                return f"{where}: bad resolution kind {res['kind']!r}"
            if not isinstance(res["answer"], str) or not res["answer"]:
                return f"{where}: resolution.answer must be a non-empty string"
        ids.append(q["id"])

        # status <-> resolution consistency
        status = q["status"]
        if status == "open":
            if res is not None:
                return f"question {q['id']}: status 'open' must have null resolution"
        elif status == "deferred" and res is None:
            pass  # deferred may be recorded with either null or a skip resolution
        elif res is None:
            return f"question {q['id']}: status '{status}' requires a resolution"
        elif res["kind"] not in ALLOWED_KINDS[status]:
            return (
                f"question {q['id']}: status '{status}' does not allow "
                f"resolution kind '{res['kind']}'"
            )

    if len(set(ids)) != len(ids):
        return "duplicate question id"
    return None


def main():
    if len(sys.argv) != 2:
        print("FAIL: usage: validate_open_questions.py <path>", file=sys.stderr)
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"FAIL: not found: {path}", file=sys.stderr)
        sys.exit(1)
    try:
        doc = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        print(f"FAIL: unparseable JSON: {exc}", file=sys.stderr)
        sys.exit(1)
    error = validate(doc)
    if error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
    n_open = sum(1 for q in doc["questions"] if q["status"] == "open")
    print(f"OK: {path} ({len(doc['questions'])} questions, {n_open} open)")


if __name__ == "__main__":
    main()
