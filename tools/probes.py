"""Lossless-refactor probe harness (developer tool, not part of the package).

Each probe is a minimal, deliberately WRONG edit to a production file
that must turn a named test file red. Run the harness before and after
a test refactor: the set of probes that go red may grow but must never
shrink, which is what "the compression lost no failure mode" means.

    python tools/probes.py                 # every probe
    python tools/probes.py T1-arity N2-envvar   # selected probes

WARNING - this tool edits files under sanity_gravity/ in place. It
restores the exact bytes it read, in a finally block and on SIGINT, but
it refuses to start when those files already have uncommitted changes so
that a crash can never be confused with your own work in progress.

Exit code 0 when every selected probe went red, 1 otherwise.
"""

from __future__ import annotations

import shutil
import signal
import subprocess
import sys
from pathlib import Path

#: Repository root: this file lives in <root>/tools/.
REPO = Path(__file__).resolve().parent.parent

S = "sanity_gravity/"
T = "tests/unit/"

#: (file to mutate, test file that must go red) -> (probe id, old, new)...
#:
#: Grouped rather than flat 5-tuples: the file pair is what the 82
#: entries repeat - two dozen probes hit manifest.py alone - and a typo
#: there reads as "PATTERN MISSING" rather than as a wrong answer.
SPECS: dict[tuple[str, str], tuple[tuple[str, str, str], ...]] = {
    (S + "domain/tags.py", T + "test_tag_grammar.py"): (
        ("T1-arity", "if len(parts) != 3:", "if len(parts) > 3:"),
        ("T2-charset", "if not SLUG_RE.match(slug):",
         "if False and not SLUG_RE.match(slug):"),
        ("T3-reserved", "if slug in RESERVED_SLUGS:", "if slug in ():"),
        ("T4-render-sep",
         'return f"{self.agent}{SEP}{self.desktop}{SEP}{self.connector}"',
         'return f"{self.agent}+{self.desktop}+{self.connector}"'),
        ("T6-parse-canonicalizes", "parts = s.split(SEP)",
         "parts = s.strip().split(SEP)"),
        ("T5-parser-arg", "def parse(cls, s: str) -> Tag:",
         "def parse(cls, s: str, parser=None) -> Tag:"),
    ),
    (S + "domain/naming.py", T + "test_naming.py"): (
        ("N1-image", 'return f"{self.IMAGE_REPO}:{self.tag}"',
         'return f"{self.IMAGE_REPO}_{self.tag}"'),
        ("N2-envvar", "str(self.tag).upper().replace('-', '_')",
         "str(self.tag).replace('-', '_')"),
        ("N3-project-guard", "if self.project is None:", "if False:"),
        ("N4-family-collapse", 'return f"{self.VOLUME_PREFIX}_{self.tag}"',
         "return self.image()"),
    ),
    (S + "domain/naming.py", T + "test_layer_grammar.py"): (
        ("L1-base-literal", 'return "_base"', 'return "_bass"'),
        ("L6-parse-inverse", 'if body.startswith("base-"):', "if False:"),
    ),
    (S + "domain/layers.py", T + "test_layer_grammar.py"): (
        ("L2-parent-rule",
         "case LayerKind.DESKTOP:\n                return LayerRef.base()",
         "case LayerKind.DESKTOP:\n                return None"),
        ("L3-occupancy", 'for field in ("agent", "desktop", "connector"):',
         "for field in ():"),
        ("L4-kind-msg", "Valid: base, desktop, agent, connector",
         "Valid: some kinds"),
        ("L5-sort-depth", "            int(self.kind),", "            -int(self.kind),"),
        ("L7-selector-arity", "if len(parts) != len(fields):",
         "if len(parts) > len(fields):"),
    ),
    (S + "domain/errors.py", T + "test_errors.py"): (
        ("E1-default-exit", "exit_code: int = 1  # class-level default",
         "exit_code: int = 0  # class-level default"),
        ("E2-hint-dropped", "        self.hint = hint", "        self.hint = None"),
        ("E3-rc0-exit", "exit_code=returncode or 1,", "exit_code=returncode,"),
        ("E4-render-quote",
         'return " ".join(shlex.quote(str(a)) for a in argv)',
         'return " ".join(str(a) for a in argv)'),
        ("E5-stderr-head", 'detail = f": {head[0]}" if head else ""',
         "detail = ': ' + ' '.join(head) if head else ''"),
    ),
    (S + "domain/tags.py", T + "test_errors.py"): (
        ("E6-tagerror-mro", "class TagError(SanityError, ValueError):",
         "class TagError(SanityError):"),
    ),
    (S + "core/registry.py", T + "test_errors.py"): (
        ("E7-unknown-msg",
         'f"Unknown agent \'{agent}\'. Valid: {\', \'.join(reg.agents.keys())}",',
         'f"Unmapped agent \'{agent}\'. Valid: {\', \'.join(reg.agents.keys())}",'),
    ),
    (S + "core/proc.py", T + "test_proc.py"): (
        ("P1-capture-collapse", ").raise_for_status(hint=hint).stdout", ").stdout"),
        ("P2-strip", 'stdout=(proc.stdout or "").strip(),',
         'stdout=(proc.stdout or ""),'),
        ("P3-missing-binary",
         "    except FileNotFoundError as exc:\n        return Completed(cmd, 127, stderr=str(exc))",
         "    except FileNotFoundError as exc:\n        raise"),
        ("P4-raise-for-status", "if not self.ok:", "if False:"),
        ("P5-shell-off",
         "rc = subprocess.call(script, shell=True, cwd=cwd, env=_merged_env(env))",
         "rc = subprocess.call(script, shell=False, cwd=cwd, env=_merged_env(env))"),
        ("P6-echo-bypass", "if reporter is not None:", "if False:"),
        ("P7-env-merge", "merged = os.environ.copy()", "merged = {}"),
    ),
    (S + "domain/plan.py", T + "test_build_kernel.py"): (
        ("K1-dedup",
         "    seen: set[LayerRef] = set()\n    for root in roots:\n        seen.add(root)\n        seen.update(root.ancestors)\n    return sorted(seen, key=lambda ref: ref.sort_key)",
         "    out: list[LayerRef] = []\n    for root in roots:\n        out.extend(root.ancestors)\n        out.append(root)\n    return out"),
        ("K4-always-build", "frozenset({LayerKind.CONNECTOR})", "frozenset()"),
        ("K6-connector-target",
         "        if layer_kind is LayerKind.CONNECTOR:\n            raise LayerError(",
         "        if False:\n            raise LayerError("),
    ),
    (S + "hooks/build.py", T + "test_build_kernel.py"): (
        ("K2-nocache-ignored", "use_probe = not ctx.no_cache and not ctx.dry_run",
         "use_probe = not ctx.dry_run"),
        ("K3-nocache-argv", '.flag("--no-cache", when=ctx.no_cache)',
         '.flag("--no-cache", when=False)'),
    ),
    (S + "core/orchestrator.py", T + "test_build_kernel.py"): (
        ("K5-phase-order", "    Phase.BUILD_PLAN,\n    Phase.BUILD_LAYER,",
         "    Phase.BUILD_LAYER,\n    Phase.BUILD_PLAN,"),
    ),
    (S + "effects/executor.py", T + "test_build_kernel.py"): (
        ("K7-dryrun-executes", "        if self.dry_run:", "        if False:"),
    ),
    (S + "hooks/build.py", T + "test_build_golden.py"): (
        ("G1-build-arg",
         'cb.opt("--build-arg", f"BASE_IMAGE={Naming.layer_image(node.parent)}")',
         "pass"),
        ("G2-cachehit-text", 'f"  Cache hit: {Naming.layer_image(ref)}"',
         'f"  cache hit: {Naming.layer_image(ref)}"'),
    ),
    (S + "compose/generators.py", T + "test_compose_golden.py"): (
        ("C1-image-expr", "image = naming.image_expr()", "image = naming.image()"),
    ),
    (S + "domain/naming.py", T + "test_compose_golden.py"): (
        ("C2-output-path", 'return f"{self.CONFIG_DIR}/docker-compose.{self.tag}.yml"',
         'return f"{self.CONFIG_DIR}/compose.{self.tag}.yml"'),
    ),
    (S + "verbs/up.py", T + "test_canonical_flow.py"): (
        ("CF1-up-raw-image",
         'check_img = try_run(("docker", "image", "inspect", naming.image()))',
         'check_img = try_run(("docker", "image", "inspect", f"sanity-gravity:{args.variant}"))'),
    ),
    (S + "verbs/pull.py", T + "test_canonical_flow.py"): (
        ("CF2-pull-raw-ref", "ghcr_image = naming.ghcr(repo_lc, version_tag)",
         'ghcr_image = f"ghcr.io/{repo_lc}-{variant}:{version_tag}"'),
    ),
    (S + "verbs/sync.py", T + "test_cli_unit.py"): (
        ("A1-sync-unquoted-container",
         'f"| docker exec -i {shlex.quote(container_name)} "',
         'f"| docker exec -i {container_name} "'),
        ("A1b-sync-unquoted-configdir",
         'f"tar -cf - -C {shlex.quote(config_dir)} "',
         'f"tar -cf - -C {config_dir} "'),
        ("M1-sync-uid-poll", "if res.ok and res.stdout.isdigit():",
         "if res.ok or res.stdout.isdigit():"),
    ),
    (S + "verbs/pull.py", T + "test_pull.py"): (
        ("A2-pull-fatal-sniffing",
         "    if tag.ok and tag.stdout:\n        return tag.stdout",
         "    if tag.ok and tag.stdout and not tag.stdout.startswith('fatal:'):\n"
         "        return tag.stdout"),
        ("M2-pull-tag-empty", "if tag.ok and tag.stdout:", "if tag.ok or tag.stdout:"),
        ("M3-pull-sha-empty", "if sha.ok and sha.stdout:", "if sha.ok or sha.stdout:"),
    ),
    (S + "effects/executor.py", T + "test_dry_run_per_verb.py"): (
        ("A3-dryrun-per-verb", "        if self.dry_run:", "        if False:"),
    ),
    (S + "plugins/manifest.py", T + "test_manifest.py"): (
        ("MA1-reserved-msg",
         """f"{p}: [plugin].slug '{slug}' is reserved: the layer-name \"""",
         """f"{p}: [plugin].slug '{slug}' is ZZZQQQ: the layer-name \""""),
        ("MA2-api-version-msg",
         """f"{p}: [plugin].api_version '{api_version}' is not supported; \"""",
         """f"{p}: ZZZQQQ '{api_version}' is not supported; \""""),
        ("MA3-ide-command-msg",
         'raise ManifestError(f"{where}.command: must not be empty")',
         'raise ManifestError(f"{where}: ZZZQQQ must not be empty")'),
        ("MA4-tier-msg",
         """f"{p}: [plugin].tier must be one of {list(TIERS)}, got '{tier}'\"""",
         """f"{p}: [plugin].ZZZQQQ must be one of {list(TIERS)}, got '{tier}'\""""),
        ("MN1-strlist-not-a-list",
         'raise ManifestError(f"{where}: expected list, got {type(value).__name__}")',
         "pass"),
        ("MN2-strlist-item-not-a-string",
         """            raise ManifestError(
                f"{where}[{i}]: expected string, got {type(item).__name__}"
            )""",
         "            pass"),
        ("MN3-int-not-an-int",
         'raise ManifestError(f"{where}: expected int, got {type(value).__name__}")',
         "pass"),
        ("MN4-int-accepts-bool",
         "if isinstance(value, bool) or not isinstance(value, int):",
         "if not isinstance(value, int):"),
        ("MN5-ports-not-a-table",
         'raise ManifestError(f"{where}: expected table")', "pass"),
        ("MN6-port-entry-not-a-table",
         'raise ManifestError(f"{sub_where}: expected table")', "pass"),
        ("MN7-plugin-not-a-table",
         'raise ManifestError(f"{p}: [plugin] must be a table")', "pass"),
        ("MN8-build-not-a-table",
         'raise ManifestError(f"{p}: [build] must be a table")', "pass"),
        ("MN9-dockerfile-path-guard",
         """            raise ManifestError(
                f"Manifest {self.slug!r} has no source_path; "
                f"dockerfile_path is unavailable"
            )""",
         "            pass"),
        ("MN10-api-version-hint", "if normalized in SUPPORTED_API_VERSIONS:",
         "if False:"),
        ("MC1-reserved-slug-off", "if slug in RESERVED_SLUGS:", "if slug in ():"),
        ("MC2-source-path-flip", "if self.source_path is None:",
         "if self.source_path is not None:"),
        ("MC3-toml-error-unwrapped",
         'raise ManifestError(f"{p}: TOML parse error: {exc}") from exc', "raise"),
        ("MC4-legacy-slug-ignored", 'if "legacy_slug" in sub:', "if False:"),
    ),
    (S + "plugins/manifest.py", T + "test_plugin_hooks.py"): (
        ("MC5-environment-dropped",
         'environment = _parse_environment(data.get("environment"), f"{p}:[environment]")',
         "environment = ()"),
        ("MC6-compose-dropped",
         'compose = _parse_compose(data.get("compose"), f"{p}:[compose]")',
         "compose = ComposeOverlay()"),
    ),
    (S + "plugins/registry.py", T + "test_plugin_registry.py"): (
        ("PR1-unknown-kind", 'raise KeyError(f"unknown plugin kind: {kind!r}")', "pass"),
        ("PR2-unknown-slug-msg",
         'raise KeyError(f"no {kind} plugin with slug {slug!r}")', "pass"),
        ("PR3-hooks-spec-guard",
         """            raise ManifestError(
                f"{hooks_path}: failed to build import spec for plugin hooks"
            )""",
         "            pass"),
    ),
    (S + "cli/io.py", T + "test_cli_io_validation.py"): (
        ("V1-username-none-guard", "if not name or not _USERNAME_RE.match(name):",
         "if not _USERNAME_RE.match(name):"),
        ("V2-project-none-guard", "if not name or not _PROJECT_NAME_RE.match(name):",
         "if not _PROJECT_NAME_RE.match(name):"),
        ("V3-project-body-underscore", r'r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$"',
         r'r"^[a-zA-Z0-9][a-zA-Z0-9.-]{0,62}$"'),
        ("V4-username-body-unicode", r'r"^[a-zA-Z_][a-zA-Z0-9_-]{0,31}$"',
         r'r"^[a-zA-Z_][\w-]{0,31}$"'),
        ("V5-project-head-no-digit", r'r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$"',
         r'r"^[a-zA-Z][a-zA-Z0-9_.-]{0,62}$"'),
        ("V6-username-body-dot", r'r"^[a-zA-Z_][a-zA-Z0-9_-]{0,31}$"',
         r'r"^[a-zA-Z_][a-zA-Z0-9_.-]{0,31}$"'),
    ),
    # The meta layer probes itself: both mutations now land in
    # tests/support.py, where the stale detector and the name-extraction
    # branch moved when the guards were de-duplicated. The act each
    # probe describes is unchanged, and so is the file that must go red.
    ("tests/support.py", T + "test_error_ratchet.py"): (
        ("R1-stale-detector", "if not actual.get(key, empty) >= want",
         "if not actual.get(key, empty) > want"),
        ("R2-bare-exit-branch",
         "    if isinstance(node, ast.Name):\n        return node.id",
         "    if isinstance(node, ast.Name):\n        return None"),
    ),
}

PROBES = [
    (pid, fname, old, new, target)
    for (fname, target), cases in SPECS.items()
    for pid, old, new in cases
]


def _purge_pyc() -> None:
    """Drop every __pycache__ under the repo.

    A same-size mutation applied and reverted inside one mtime second
    passes cpython's (mtime, size) pyc validation, so the stale MUTANT
    bytecode would shadow the restored source on the next import.
    """
    for cache in REPO.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def _mutated_paths() -> list[str]:
    """Every file this run would edit, repo-relative and unique.

    Derived from PROBES, not hard-coded, so a probe that starts mutating
    a new file is covered by the dirty-tree refusal automatically. Note
    this is NOT limited to production: the guard-the-guard probes mutate
    tests/support.py, because the shared comparison the ratchets trust
    lives there.
    """
    return sorted({fname for _, fname, _, _, _ in PROBES})


def _refuse_when_dirty() -> str | None:
    """Return an error message when the files we mutate are not pristine.

    The harness restores what it read, so a dirty tree is not a
    correctness problem for the harness - it is a safety problem for
    YOU: if the process is killed between write and restore, the only
    way to tell a leftover mutation from your own edit is that there
    were no edits to begin with.
    """
    probe = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        capture_output=True, text=True, cwd=REPO,
    )
    if probe.returncode != 0:
        # A plain (non-git) copy - the harness still works, but nothing
        # can vouch that a leftover mutation is not your own edit. Say so
        # rather than degrade silently: a safety check that disappears
        # without a word is worse than one that was never claimed.
        print(
            "warning: not a git checkout - skipping the pristine-tree check. "
            "A crash mid-probe will leave a mutation you cannot distinguish "
            "from your own work.",
            file=sys.stderr,
        )
        return None
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", *_mutated_paths()],
        capture_output=True, text=True, cwd=REPO,
    )
    dirty = [ln for ln in status.stdout.splitlines() if ln.strip()]
    if not dirty:
        return None
    listing = "\n  ".join(dirty)
    return (
        "refusing to run: files this harness mutates have uncommitted "
        "changes.\n  " + listing +
        "\n\nCommit or stash them first - the harness must be the only "
        "thing editing these files. (The set is derived from PROBES and "
        "includes tests/support.py, not just production modules.)"
    )


def run(selected: set[str] | None = None) -> int:
    refusal = _refuse_when_dirty()
    if refusal:
        print(refusal, file=sys.stderr)
        return 2

    unknown = (selected or set()) - {pid for pid, *_ in PROBES}
    if unknown:
        print(f"unknown probe id(s): {sorted(unknown)}", file=sys.stderr)
        return 2

    failures: list[str] = []
    for pid, fname, old, new, target in PROBES:
        if selected and pid not in selected:
            continue
        path = REPO / fname
        original = path.read_text()
        if old not in original:
            print(f"[{pid}] PATTERN MISSING in {fname}")
            failures.append(pid)
            continue

        restored = False

        def restore(_signum=None, _frame=None, _path=path, _text=original) -> None:
            _path.write_text(_text)
            _purge_pyc()

        previous = signal.signal(signal.SIGINT, restore)
        try:
            path.write_text(original.replace(old, new, 1))
            _purge_pyc()
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", target, "-q", "-x",
                 "--no-header", "-p", "no:cacheprovider"],
                capture_output=True, text=True, cwd=REPO,
            )
            if proc.returncode == 0:
                print(f"[{pid}] NOT DETECTED (suite stayed green)")
                failures.append(pid)
            else:
                lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
                tail = lines[-1].strip()[:80] if lines else ""
                print(f"[{pid}] red as required :: {tail}")
        finally:
            # Restore the bytes we read rather than `git checkout --`:
            # that would fail silently in a non-git copy and leave the
            # mutation live, poisoning every later probe.
            restore()
            restored = True
            signal.signal(signal.SIGINT, previous)
        assert restored

    print("PROBES-FAILED:", failures if failures else "none")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run(set(sys.argv[1:])))
