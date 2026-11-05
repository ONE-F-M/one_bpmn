#!/usr/bin/env python3
"""Structure check for pull requests.

Looks only at what a pull request changes (files changed, lines added) and fails
when new code breaks the layout or code-safety rules. Breaches that already
exist are listed in .github/structure_baseline.txt and are allowed to stay, but
never to get worse.

Rules
  size           Python file over PY_MAX_LINES lines, Vue file over VUE_MAX_LINES lines.
  work-item-id   A work-item ID on an added line (comment, docstring, string, patches.txt)
                 or in the name of an added file.
  permissions    An added line that sets the ignore_permissions flag to True, with no
                 reason comment on the same line.
  raw-sql        An added line that makes a raw frappe.db SQL call, with no reason
                 comment on the same line.
  test-location  An added test file outside a doctype folder or a tests/ folder.
  import         An added import of SpiffWorkflow outside the engine, or of anthropic,
                 openai or google.genai outside the model adapters.
  baseline       A baseline entry added or made larger needs approval from a code owner.

Baseline format, one entry per line ("#" starts a comment):
  size <path> <line count>
  test-location <path>

Limits and locations are those assumed from the work item; the Processa
Engineering Standard was not available in the repository when this was written.
Change the constants below if the Standard says otherwise.

Usage
  check_structure.py --base origin/staging [--approvers login1,login2]
  check_structure.py --write-baseline        # regenerate the baseline from the tree
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

PY_MAX_LINES = 800
VUE_MAX_LINES = 500

BASELINE_PATH = ".github/structure_baseline.txt"
CODEOWNERS_PATH = ".github/CODEOWNERS"

# Where the restricted imports are allowed (path prefixes, repo-relative).
ENGINE_PREFIXES = ("one_bpmn/one_bpmn/engine.py", "one_bpmn/one_bpmn/engine/")
ADAPTER_PREFIXES = ("one_bpmn/agents/llm_provider/",)

WORK_ITEM_ID = re.compile(r"(?<![A-Za-z0-9])WI-\d+")
IGNORE_PERMISSIONS = re.compile(r"ignore_permissions\s*=\s*True")
RAW_SQL = re.compile(r"frappe\.db\.sql\s*\(")
PRAGMA_ONLY = re.compile(r"^(noqa|nosec|type:\s*ignore|pylint:|fmt:|pragma)", re.IGNORECASE)

RESTRICTED_IMPORTS = (
	("SpiffWorkflow", re.compile(r"^\s*(?:import|from)\s+SpiffWorkflow\b"), ENGINE_PREFIXES, "the engine"),
	("anthropic", re.compile(r"^\s*(?:import|from)\s+anthropic\b"), ADAPTER_PREFIXES, "the model adapters"),
	("openai", re.compile(r"^\s*(?:import|from)\s+openai\b"), ADAPTER_PREFIXES, "the model adapters"),
	(
		"google.genai",
		re.compile(r"^\s*(?:import\s+google\.genai\b|from\s+google\.genai\b|from\s+google\s+import\s+genai\b)"),
		ADAPTER_PREFIXES,
		"the model adapters",
	),
)

ID_EXTENSIONS = (".py", ".vue", ".js", ".ts", ".jsx", ".tsx")

Baseline = Dict[Tuple[str, str], int]


@dataclass
class Change:
	"""One changed file: its status (A added, M modified, D deleted), full text and added lines."""

	path: str
	status: str
	text: Optional[str] = None
	added: List[Tuple[int, str]] = field(default_factory=list)

	@classmethod
	def new_file(cls, path: str, text: str) -> "Change":
		return cls(path, "A", text, list(enumerate(text.splitlines(), 1)))

	@classmethod
	def modified(cls, path: str, text: str, added: Sequence[Tuple[int, str]]) -> "Change":
		return cls(path, "M", text, list(added))

	@classmethod
	def deleted(cls, path: str) -> "Change":
		return cls(path, "D")


@dataclass
class Finding:
	path: str
	line: Optional[int]
	rule: str
	message: str

	def __str__(self) -> str:
		where = f"{self.path}:{self.line}" if self.line else self.path
		return f"{where}: [{self.rule}] {self.message}"


@dataclass
class Result:
	failures: List[Finding] = field(default_factory=list)
	notices: List[str] = field(default_factory=list)

	@property
	def ok(self) -> bool:
		return not self.failures


# ---------------------------------------------------------------- baseline


def parse_baseline(text: str) -> Baseline:
	entries: Baseline = {}
	for raw in text.splitlines():
		line = raw.strip()
		if not line or line.startswith("#"):
			continue
		parts = line.split()
		if len(parts) < 2:
			continue
		value = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
		entries[(parts[0], parts[1])] = value
	return entries


def format_baseline(entries: Baseline) -> str:
	header = [
		"# Known structure breaches. The structure check lets these stay but never get worse.",
		"# Delete an entry when the breach is fixed. Adding or raising an entry needs a code owner's approval.",
		"# Regenerate with: python .github/scripts/check_structure.py --write-baseline",
		"# Formats: size <path> <line count>   |   test-location <path>",
	]
	lines = []
	for (rule, path), value in sorted(entries.items(), key=lambda item: (item[0][0], item[0][1])):
		lines.append(f"{rule} {path} {value}" if rule == "size" else f"{rule} {path}")
	return "\n".join(header + lines) + "\n"


# ---------------------------------------------------------------- helpers


def size_limit(path: str) -> Optional[int]:
	if path.endswith(".py"):
		return PY_MAX_LINES
	if path.endswith(".vue"):
		return VUE_MAX_LINES
	return None


def line_count(text: str) -> int:
	return len(text.splitlines())


def is_test_file(path: str) -> bool:
	name = path.rsplit("/", 1)[-1]
	return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def in_allowed_test_location(path: str) -> bool:
	"""A test file belongs in a tests/ folder (one_bpmn/tests/ or a module's) or in a folder under doctype/."""
	folders = path.split("/")[:-1]
	if "tests" in folders:
		return True
	return "doctype" in folders and folders.index("doctype") < len(folders) - 1


def has_reason_comment(line: str, start: int) -> bool:
	idx = line.find("#", start)
	if idx == -1:
		return False
	comment = line[idx + 1 :].strip()
	return len(comment) >= 3 and not PRAGMA_ONLY.match(comment)


def allowed_prefix(path: str, prefixes: Sequence[str]) -> bool:
	return any(path.startswith(prefix) for prefix in prefixes)


def carries_work_item_ids(path: str) -> bool:
	return path.endswith(ID_EXTENSIONS) or path.rsplit("/", 1)[-1] == "patches.txt"


# ---------------------------------------------------------------- rules


def check_size(change: Change, baseline: Baseline, result: Result) -> None:
	limit = size_limit(change.path)
	if limit is None or change.status == "D" or change.text is None:
		return
	size = line_count(change.text)
	recorded = baseline.get(("size", change.path))
	if size <= limit:
		if recorded is not None:
			result.notices.append(
				f"{change.path} is now {size} lines, within the {limit}-line limit. "
				f"Please delete its baseline entry from {BASELINE_PATH}."
			)
		return
	if recorded is None:
		result.failures.append(
			Finding(change.path, None, "size", f"{size} lines, over the limit of {limit} lines")
		)
	elif size > recorded:
		result.failures.append(
			Finding(
				change.path,
				None,
				"size",
				f"{size} lines, up from {recorded} in the baseline (limit {limit}); a file in the baseline may not grow",
			)
		)
	elif size < recorded:
		result.notices.append(
			f"{change.path} shrank to {size} lines (baseline says {recorded}). "
			f"Please lower its baseline entry in {BASELINE_PATH}."
		)


def check_work_item_ids(change: Change, result: Result) -> None:
	if change.status == "D":
		return
	if change.status == "A" and WORK_ITEM_ID.search(change.path):
		result.failures.append(Finding(change.path, None, "work-item-id", "file name contains a work-item ID"))
	if not carries_work_item_ids(change.path):
		return
	for number, text in change.added:
		match = WORK_ITEM_ID.search(text)
		if match:
			result.failures.append(
				Finding(change.path, number, "work-item-id", f"work-item ID {match.group(0)} on an added line")
			)


def check_unsafe_calls(change: Change, result: Result) -> None:
	if change.status == "D" or not change.path.endswith(".py"):
		return
	for number, text in change.added:
		if text.lstrip().startswith("#"):
			continue
		for rule, pattern, what in (
			("permissions", IGNORE_PERMISSIONS, "permission checks are skipped"),
			("raw-sql", RAW_SQL, "raw SQL call"),
		):
			match = pattern.search(text)
			if match and not has_reason_comment(text, match.end()):
				result.failures.append(
					Finding(change.path, number, rule, f"{what} with no reason comment on the same line")
				)


def check_test_location(change: Change, baseline: Baseline, result: Result) -> None:
	if not is_test_file(change.path):
		return
	if change.status == "D":
		return
	if change.status == "A" and not in_allowed_test_location(change.path):
		result.failures.append(
			Finding(
				change.path,
				None,
				"test-location",
				"test file must live in a doctype folder, a module tests/ folder or one_bpmn/tests/",
			)
		)


def check_imports(change: Change, result: Result) -> None:
	if change.status == "D" or not change.path.endswith(".py"):
		return
	for number, text in change.added:
		for name, pattern, prefixes, where in RESTRICTED_IMPORTS:
			if pattern.search(text) and not allowed_prefix(change.path, prefixes):
				result.failures.append(
					Finding(change.path, number, "import", f"{name} may only be imported inside {where}")
				)


def check_deleted(change: Change, baseline: Baseline, result: Result) -> None:
	if change.status != "D":
		return
	for (rule, path) in baseline:
		if path == change.path:
			result.notices.append(
				f"{change.path} was removed, so its '{rule}' breach is gone. "
				f"Please delete its baseline entry from {BASELINE_PATH}."
			)


def owners_for(path: str, codeowners: str) -> List[str]:
	owners: List[str] = []
	for raw in codeowners.splitlines():
		line = raw.strip()
		if not line or line.startswith("#"):
			continue
		pattern, *names = line.split()
		if _codeowners_match(pattern, path):
			owners = [name.lstrip("@").lower() for name in names]
	return owners


def _codeowners_match(pattern: str, path: str) -> bool:
	if pattern.startswith("/"):
		pattern = pattern[1:]
		if pattern.endswith("/"):
			return path.startswith(pattern)
		return path == pattern or path.startswith(pattern + "/") or fnmatch.fnmatch(path, pattern)
	return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path.rsplit("/", 1)[-1], pattern)


def baseline_additions(head: Baseline, base: Baseline) -> List[Tuple[str, str, int]]:
	"""Entries that are new in the head baseline, or whose number went up."""
	return [
		(rule, path, value)
		for (rule, path), value in sorted(head.items())
		if (rule, path) not in base or value > base[(rule, path)]
	]


def check_baseline_approval(
	head: Baseline,
	base: Baseline,
	approvers: Sequence[str],
	codeowners: str,
	result: Result,
) -> None:
	additions = baseline_additions(head, base)
	if not additions:
		return
	owners = owners_for(BASELINE_PATH, codeowners)
	approved = {name.lstrip("@").lower() for name in approvers if name.strip()}
	if owners and approved.intersection(owners):
		return
	asked = ", ".join("@" + owner for owner in owners) or "(no code owner found in CODEOWNERS)"
	for rule, path, value in additions:
		entry = f"{rule} {path} {value}" if rule == "size" else f"{rule} {path}"
		result.failures.append(
			Finding(
				BASELINE_PATH,
				None,
				"baseline",
				f"entry added or raised: '{entry}'. Needs approval from a code owner: {asked}",
			)
		)


# ---------------------------------------------------------------- driver


def run_checks(
	changes: Sequence[Change],
	baseline: Baseline,
	base_baseline: Optional[Baseline] = None,
	approvers: Sequence[str] = (),
	codeowners: str = "",
) -> Result:
	result = Result()
	for change in changes:
		check_size(change, baseline, result)
		check_work_item_ids(change, result)
		check_unsafe_calls(change, result)
		check_test_location(change, baseline, result)
		check_imports(change, result)
		check_deleted(change, baseline, result)
	check_baseline_approval(baseline, base_baseline or {}, approvers, codeowners, result)
	return result


def generate_baseline(files: Dict[str, str]) -> Baseline:
	"""The baseline for a whole tree: every file over its limit, every misplaced test file."""
	entries: Baseline = {}
	for path, text in files.items():
		limit = size_limit(path)
		if limit is not None and line_count(text) > limit:
			entries[("size", path)] = line_count(text)
		if is_test_file(path) and not in_allowed_test_location(path):
			entries[("test-location", path)] = 0
	return entries


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def parse_diff(diff: str) -> Dict[str, Tuple[str, List[Tuple[int, str]]]]:
	"""Read `git diff --no-renames -U0` output into {path: (status, added lines)}."""
	files: Dict[str, Tuple[str, List[Tuple[int, str]]]] = {}
	path: Optional[str] = None
	line_no = 0
	for raw in diff.splitlines():
		if raw.startswith("diff --git "):
			path = raw.rsplit(" b/", 1)[-1]
			files[path] = ("M", [])
			continue
		if path is None:
			continue
		status, added = files[path]
		if raw.startswith("new file mode"):
			files[path] = ("A", added)
		elif raw.startswith("deleted file mode"):
			files[path] = ("D", added)
		elif raw.startswith("@@"):
			match = _HUNK.match(raw)
			line_no = int(match.group(1)) if match else 0
		elif raw.startswith("+") and not raw.startswith("+++"):
			added.append((line_no, raw[1:]))
			line_no += 1
	return files


def _git(args: List[str], root: str) -> str:
	return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


def _git_show(ref: str, path: str, root: str) -> str:
	try:
		return _git(["show", f"{ref}:{path}"], root)
	except subprocess.CalledProcessError:
		return ""


def collect_changes(base: str, root: str) -> List[Change]:
	diff = _git(["diff", "--no-renames", "-U0", "--no-color", f"{base}...HEAD"], root)
	changes = []
	for path, (status, added) in parse_diff(diff).items():
		if status == "D":
			changes.append(Change.deleted(path))
			continue
		full = os.path.join(root, path)
		try:
			with open(full, encoding="utf-8", errors="replace") as handle:
				text = handle.read()
		except OSError:
			continue
		changes.append(Change(path, status, text, added))
	return changes


def write_baseline(root: str) -> None:
	files: Dict[str, str] = {}
	for path in _git(["ls-files"], root).splitlines():
		if size_limit(path) is None and not is_test_file(path):
			continue
		try:
			with open(os.path.join(root, path), encoding="utf-8", errors="replace") as handle:
				files[path] = handle.read()
		except OSError:
			continue
	entries = generate_baseline(files)
	with open(os.path.join(root, BASELINE_PATH), "w", encoding="utf-8") as handle:
		handle.write(format_baseline(entries))
	print(f"Wrote {len(entries)} entries to {BASELINE_PATH}")


def main(argv: Optional[Sequence[str]] = None) -> int:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("--base", default=None, help="Base ref to diff against, e.g. origin/staging")
	parser.add_argument(
		"--approvers",
		default=os.environ.get("APPROVERS", ""),
		help="Comma-separated logins that have approved the pull request",
	)
	parser.add_argument("--root", default=None, help="Repository root (default: git top level)")
	parser.add_argument("--write-baseline", action="store_true", help="Regenerate the baseline from the tree")
	args = parser.parse_args(argv)

	root = args.root or _git(["rev-parse", "--show-toplevel"], os.getcwd()).strip()
	if args.write_baseline:
		write_baseline(root)
		return 0
	if not args.base:
		parser.error("--base is required")

	baseline_file = os.path.join(root, BASELINE_PATH)
	head_text = ""
	if os.path.exists(baseline_file):
		with open(baseline_file, encoding="utf-8") as handle:
			head_text = handle.read()
	codeowners = ""
	codeowners_file = os.path.join(root, CODEOWNERS_PATH)
	if os.path.exists(codeowners_file):
		with open(codeowners_file, encoding="utf-8") as handle:
			codeowners = handle.read()

	changes = collect_changes(args.base, root)
	result = run_checks(
		changes,
		parse_baseline(head_text),
		parse_baseline(_git_show(args.base, BASELINE_PATH, root)),
		[name for name in args.approvers.split(",") if name.strip()],
		codeowners,
	)

	for notice in result.notices:
		print(f"NOTICE: {notice}")
	for finding in result.failures:
		print(f"FAIL: {finding}")
	print(f"Checked {len(changes)} changed file(s): {len(result.failures)} failure(s), {len(result.notices)} notice(s).")
	return 0 if result.ok else 1


if __name__ == "__main__":
	sys.exit(main())
