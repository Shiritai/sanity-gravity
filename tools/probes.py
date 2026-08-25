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

T = "tests/unit/"
PROBES = [
    ("T1-arity", "sanity_gravity/domain/tags.py",
     "if len(parts) != 3:", "if len(parts) > 3:", T + "test_tag_grammar.py"),
    ("T2-charset", "sanity_gravity/domain/tags.py",
     "if not SLUG_RE.match(slug):", "if False and not SLUG_RE.match(slug):",
     T + "test_tag_grammar.py"),
    ("T3-reserved", "sanity_gravity/domain/tags.py",
     "if slug in RESERVED_SLUGS:", "if slug in ():", T + "test_tag_grammar.py"),
    ("T4-render-sep", "sanity_gravity/domain/tags.py",
     'return f"{self.agent}{SEP}{self.desktop}{SEP}{self.connector}"',
     'return f"{self.agent}+{self.desktop}+{self.connector}"',
     T + "test_tag_grammar.py"),
    ("T6-parse-canonicalizes", "sanity_gravity/domain/tags.py",
     "parts = s.split(SEP)",
     "parts = s.strip().split(SEP)",
     T + "test_tag_grammar.py"),
    ("T5-parser-arg", "sanity_gravity/domain/tags.py",
     "def parse(cls, s: str) -> Tag:",
     "def parse(cls, s: str, parser=None) -> Tag:", T + "test_tag_grammar.py"),
    ("N1-image", "sanity_gravity/domain/naming.py",
     'return f"{self.IMAGE_REPO}:{self.tag}"',
     'return f"{self.IMAGE_REPO}_{self.tag}"', T + "test_naming.py"),
    ("N2-envvar", "sanity_gravity/domain/naming.py",
     "str(self.tag).upper().replace('-', '_')",
     "str(self.tag).replace('-', '_')", T + "test_naming.py"),
    ("N3-project-guard", "sanity_gravity/domain/naming.py",
     "if self.project is None:", "if False:", T + "test_naming.py"),
    ("N4-family-collapse", "sanity_gravity/domain/naming.py",
     'return f"{self.VOLUME_PREFIX}_{self.tag}"',
     "return self.image()", T + "test_naming.py"),
    ("L1-base-literal", "sanity_gravity/domain/naming.py",
     'return "_base"', 'return "_bass"', T + "test_layer_grammar.py"),
    ("L2-parent-rule", "sanity_gravity/domain/layers.py",
     "case LayerKind.DESKTOP:\n                return LayerRef.base()",
     "case LayerKind.DESKTOP:\n                return None",
     T + "test_layer_grammar.py"),
    ("L3-occupancy", "sanity_gravity/domain/layers.py",
     'for field in ("agent", "desktop", "connector"):',
     "for field in ():", T + "test_layer_grammar.py"),
    ("L4-kind-msg", "sanity_gravity/domain/layers.py",
     "Valid: base, desktop, agent, connector",
     "Valid: some kinds", T + "test_layer_grammar.py"),
    ("L5-sort-depth", "sanity_gravity/domain/layers.py",
     "            int(self.kind),", "            -int(self.kind),",
     T + "test_layer_grammar.py"),
    ("L6-parse-inverse", "sanity_gravity/domain/naming.py",
     'if body.startswith("base-"):', "if False:", T + "test_layer_grammar.py"),
    ("L7-selector-arity", "sanity_gravity/domain/layers.py",
     "if len(parts) != len(fields):", "if len(parts) > len(fields):",
     T + "test_layer_grammar.py"),
    ("E1-default-exit", "sanity_gravity/domain/errors.py",
     "exit_code: int = 1  # class-level default",
     "exit_code: int = 0  # class-level default", T + "test_errors.py"),
    ("E2-hint-dropped", "sanity_gravity/domain/errors.py",
     "        self.hint = hint", "        self.hint = None",
     T + "test_errors.py"),
    ("E3-rc0-exit", "sanity_gravity/domain/errors.py",
     "exit_code=returncode or 1,", "exit_code=returncode,",
     T + "test_errors.py"),
    ("E4-render-quote", "sanity_gravity/domain/errors.py",
     'return " ".join(shlex.quote(str(a)) for a in argv)',
     'return " ".join(str(a) for a in argv)', T + "test_errors.py"),
    ("E5-stderr-head", "sanity_gravity/domain/errors.py",
     'detail = f": {head[0]}" if head else ""',
     "detail = ': ' + ' '.join(head) if head else ''", T + "test_errors.py"),
    ("E6-tagerror-mro", "sanity_gravity/domain/tags.py",
     "class TagError(SanityError, ValueError):",
     "class TagError(SanityError):", T + "test_errors.py"),
    ("E7-unknown-msg", "sanity_gravity/core/registry.py",
     'f"Unknown agent \'{agent}\'. Valid: {\', \'.join(reg.agents.keys())}",',
     'f"Unmapped agent \'{agent}\'. Valid: {\', \'.join(reg.agents.keys())}",',
     T + "test_errors.py"),
    ("P1-capture-collapse", "sanity_gravity/core/proc.py",
     ").raise_for_status(hint=hint).stdout",
     ").stdout", T + "test_proc.py"),
    ("P2-strip", "sanity_gravity/core/proc.py",
     'stdout=(proc.stdout or "").strip(),', 'stdout=(proc.stdout or ""),',
     T + "test_proc.py"),
    ("P3-missing-binary", "sanity_gravity/core/proc.py",
     "    except FileNotFoundError as exc:\n        return Completed(cmd, 127, stderr=str(exc))",
     "    except FileNotFoundError as exc:\n        raise",
     T + "test_proc.py"),
    ("P4-raise-for-status", "sanity_gravity/core/proc.py",
     "if not self.ok:", "if False:", T + "test_proc.py"),
    ("P5-shell-off", "sanity_gravity/core/proc.py",
     "rc = subprocess.call(script, shell=True, cwd=cwd, env=_merged_env(env))",
     "rc = subprocess.call(script, shell=False, cwd=cwd, env=_merged_env(env))",
     T + "test_proc.py"),
    ("P6-echo-bypass", "sanity_gravity/core/proc.py",
     "if reporter is not None:", "if False:", T + "test_proc.py"),
    ("P7-env-merge", "sanity_gravity/core/proc.py",
     "merged = os.environ.copy()", "merged = {}", T + "test_proc.py"),
    ("K1-dedup", "sanity_gravity/domain/plan.py",
     "    seen: set[LayerRef] = set()\n    for root in roots:\n        seen.add(root)\n        seen.update(root.ancestors)\n    return sorted(seen, key=lambda ref: ref.sort_key)",
     "    out: list[LayerRef] = []\n    for root in roots:\n        out.extend(root.ancestors)\n        out.append(root)\n    return out",
     T + "test_build_kernel.py"),
    ("K2-nocache-ignored", "sanity_gravity/hooks/build.py",
     "use_probe = not ctx.no_cache and not ctx.dry_run",
     "use_probe = not ctx.dry_run", T + "test_build_kernel.py"),
    ("K3-nocache-argv", "sanity_gravity/hooks/build.py",
     '.flag("--no-cache", when=ctx.no_cache)', '.flag("--no-cache", when=False)',
     T + "test_build_kernel.py"),
    ("K4-always-build", "sanity_gravity/domain/plan.py",
     "frozenset({LayerKind.CONNECTOR})", "frozenset()",
     T + "test_build_kernel.py"),
    ("K5-phase-order", "sanity_gravity/core/orchestrator.py",
     "    Phase.BUILD_PLAN,\n    Phase.BUILD_LAYER,",
     "    Phase.BUILD_LAYER,\n    Phase.BUILD_PLAN,",
     T + "test_build_kernel.py"),
    ("K6-connector-target", "sanity_gravity/domain/plan.py",
     "        if layer_kind is LayerKind.CONNECTOR:\n            raise LayerError(",
     "        if False:\n            raise LayerError(",
     T + "test_build_kernel.py"),
    ("K7-dryrun-executes", "sanity_gravity/effects/executor.py",
     "        if self.dry_run:", "        if False:",
     T + "test_build_kernel.py"),
    ("G1-build-arg", "sanity_gravity/hooks/build.py",
     'cb.opt("--build-arg", f"BASE_IMAGE={Naming.layer_image(node.parent)}")',
     "pass",
     T + "test_build_golden.py"),
    ("G2-cachehit-text", "sanity_gravity/hooks/build.py",
     'f"  Cache hit: {Naming.layer_image(ref)}"',
     'f"  cache hit: {Naming.layer_image(ref)}"',
     T + "test_build_golden.py"),
    ("C1-image-expr", "sanity_gravity/compose/generators.py",
     "image = naming.image_expr()", "image = naming.image()",
     T + "test_compose_golden.py"),
    ("C2-output-path", "sanity_gravity/domain/naming.py",
     'return f"{self.CONFIG_DIR}/docker-compose.{self.tag}.yml"',
     'return f"{self.CONFIG_DIR}/compose.{self.tag}.yml"',
     T + "test_compose_golden.py"),
    ("CF1-up-raw-image", "sanity_gravity/verbs/up.py",
     'check_img = try_run(("docker", "image", "inspect", naming.image()))',
     'check_img = try_run(("docker", "image", "inspect", f"sanity-gravity:{args.variant}"))',
     T + "test_canonical_flow.py"),
    ("CF2-pull-raw-ref", "sanity_gravity/verbs/pull.py",
     "ghcr_image = naming.ghcr(repo_lc, version_tag)",
     'ghcr_image = f"ghcr.io/{repo_lc}-{variant}:{version_tag}"',
     T + "test_canonical_flow.py"),
    ("A1-sync-unquoted-container", "sanity_gravity/verbs/sync.py",
     'f"| docker exec -i {shlex.quote(container_name)} "',
     'f"| docker exec -i {container_name} "',
     T + "test_cli_unit.py"),
    ("A1b-sync-unquoted-configdir", "sanity_gravity/verbs/sync.py",
     'f"tar -cf - -C {shlex.quote(config_dir)} "',
     'f"tar -cf - -C {config_dir} "',
     T + "test_cli_unit.py"),
    ("A2-pull-fatal-sniffing", "sanity_gravity/verbs/pull.py",
     "    if tag.ok and tag.stdout:\n        return tag.stdout",
     "    if tag.ok and tag.stdout and not tag.stdout.startswith('fatal:'):\n"
     "        return tag.stdout",
     T + "test_pull.py"),
    ("A3-dryrun-per-verb", "sanity_gravity/effects/executor.py",
     "        if self.dry_run:", "        if False:",
     T + "test_dry_run_per_verb.py"),
    ("M1-sync-uid-poll", "sanity_gravity/verbs/sync.py",
     "if res.ok and res.stdout.isdigit():",
     "if res.ok or res.stdout.isdigit():", T + "test_cli_unit.py"),
    ("M2-pull-tag-empty", "sanity_gravity/verbs/pull.py",
     "if tag.ok and tag.stdout:", "if tag.ok or tag.stdout:",
     T + "test_pull.py"),
    ("M3-pull-sha-empty", "sanity_gravity/verbs/pull.py",
     "if sha.ok and sha.stdout:", "if sha.ok or sha.stdout:",
     T + "test_pull.py"),
    ("MA1-reserved-msg", "sanity_gravity/plugins/manifest.py",
     """f"{p}: [plugin].slug '{slug}' is reserved: the layer-name \"""",
     """f"{p}: [plugin].slug '{slug}' is ZZZQQQ: the layer-name \"""",
     T + "test_manifest.py"),
    ("MA2-api-version-msg", "sanity_gravity/plugins/manifest.py",
     """f"{p}: [plugin].api_version '{api_version}' is not supported; \"""",
     """f"{p}: ZZZQQQ '{api_version}' is not supported; \"""",
     T + "test_manifest.py"),
    ("MA3-ide-command-msg", "sanity_gravity/plugins/manifest.py",
     'raise ManifestError(f"{where}.command: must not be empty")',
     'raise ManifestError(f"{where}: ZZZQQQ must not be empty")',
     T + "test_manifest.py"),
    ("MA4-tier-msg", "sanity_gravity/plugins/manifest.py",
     """f"{p}: [plugin].tier must be one of {list(TIERS)}, got '{tier}'\"""",
     """f"{p}: [plugin].ZZZQQQ must be one of {list(TIERS)}, got '{tier}'\"""",
     T + "test_manifest.py"),
    ("MN1-strlist-not-a-list", "sanity_gravity/plugins/manifest.py",
     'raise ManifestError(f"{where}: expected list, got {type(value).__name__}")',
     "pass", T + "test_manifest.py"),
    ("MN2-strlist-item-not-a-string", "sanity_gravity/plugins/manifest.py",
     """            raise ManifestError(
                f"{where}[{i}]: expected string, got {type(item).__name__}"
            )""",
     "            pass", T + "test_manifest.py"),
    ("MN3-int-not-an-int", "sanity_gravity/plugins/manifest.py",
     'raise ManifestError(f"{where}: expected int, got {type(value).__name__}")',
     "pass", T + "test_manifest.py"),
    ("MN4-int-accepts-bool", "sanity_gravity/plugins/manifest.py",
     "if isinstance(value, bool) or not isinstance(value, int):",
     "if not isinstance(value, int):", T + "test_manifest.py"),
    ("MN5-ports-not-a-table", "sanity_gravity/plugins/manifest.py",
     'raise ManifestError(f"{where}: expected table")', "pass",
     T + "test_manifest.py"),
    ("MN6-port-entry-not-a-table", "sanity_gravity/plugins/manifest.py",
     'raise ManifestError(f"{sub_where}: expected table")', "pass",
     T + "test_manifest.py"),
    ("MN7-plugin-not-a-table", "sanity_gravity/plugins/manifest.py",
     'raise ManifestError(f"{p}: [plugin] must be a table")', "pass",
     T + "test_manifest.py"),
    ("MN8-build-not-a-table", "sanity_gravity/plugins/manifest.py",
     'raise ManifestError(f"{p}: [build] must be a table")', "pass",
     T + "test_manifest.py"),
    ("MN9-dockerfile-path-guard", "sanity_gravity/plugins/manifest.py",
     """            raise ManifestError(
                f"Manifest {self.slug!r} has no source_path; "
                f"dockerfile_path is unavailable"
            )""",
     "            pass", T + "test_manifest.py"),
    ("MN10-api-version-hint", "sanity_gravity/plugins/manifest.py",
     "if normalized in SUPPORTED_API_VERSIONS:", "if False:",
     T + "test_manifest.py"),
    ("MC1-reserved-slug-off", "sanity_gravity/plugins/manifest.py",
     "if slug in RESERVED_SLUGS:", "if slug in ():", T + "test_manifest.py"),
    ("MC2-source-path-flip", "sanity_gravity/plugins/manifest.py",
     "if self.source_path is None:", "if self.source_path is not None:",
     T + "test_manifest.py"),
    ("MC3-toml-error-unwrapped", "sanity_gravity/plugins/manifest.py",
     'raise ManifestError(f"{p}: TOML parse error: {exc}") from exc',
     "raise", T + "test_manifest.py"),
    ("MC4-legacy-slug-ignored", "sanity_gravity/plugins/manifest.py",
     'if "legacy_slug" in sub:', "if False:", T + "test_manifest.py"),
    ("MC5-environment-dropped", "sanity_gravity/plugins/manifest.py",
     'environment = _parse_environment(data.get("environment"), f"{p}:[environment]")',
     "environment = ()", T + "test_plugin_hooks.py"),
    ("MC6-compose-dropped", "sanity_gravity/plugins/manifest.py",
     'compose = _parse_compose(data.get("compose"), f"{p}:[compose]")',
     "compose = ComposeOverlay()", T + "test_plugin_hooks.py"),
    ("PR1-unknown-kind", "sanity_gravity/plugins/registry.py",
     'raise KeyError(f"unknown plugin kind: {kind!r}")', "pass",
     T + "test_plugin_registry.py"),
    ("PR2-unknown-slug-msg", "sanity_gravity/plugins/registry.py",
     'raise KeyError(f"no {kind} plugin with slug {slug!r}")', "pass",
     T + "test_plugin_registry.py"),
    ("PR3-hooks-spec-guard", "sanity_gravity/plugins/registry.py",
     """            raise ManifestError(
                f"{hooks_path}: failed to build import spec for plugin hooks"
            )""",
     "            pass", T + "test_plugin_registry.py"),
    ("V1-username-none-guard", "sanity_gravity/cli/io.py",
     "if not name or not _USERNAME_RE.match(name):",
     "if not _USERNAME_RE.match(name):", T + "test_cli_io_validation.py"),
    ("V2-project-none-guard", "sanity_gravity/cli/io.py",
     "if not name or not _PROJECT_NAME_RE.match(name):",
     "if not _PROJECT_NAME_RE.match(name):", T + "test_cli_io_validation.py"),
    ("V3-project-body-underscore", "sanity_gravity/cli/io.py",
     r'r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$"',
     r'r"^[a-zA-Z0-9][a-zA-Z0-9.-]{0,62}$"', T + "test_cli_io_validation.py"),
    ("V4-username-body-unicode", "sanity_gravity/cli/io.py",
     r'r"^[a-zA-Z_][a-zA-Z0-9_-]{0,31}$"',
     r'r"^[a-zA-Z_][\w-]{0,31}$"', T + "test_cli_io_validation.py"),
    ("V5-project-head-no-digit", "sanity_gravity/cli/io.py",
     r'r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$"',
     r'r"^[a-zA-Z][a-zA-Z0-9_.-]{0,62}$"', T + "test_cli_io_validation.py"),
    ("V6-username-body-dot", "sanity_gravity/cli/io.py",
     r'r"^[a-zA-Z_][a-zA-Z0-9_-]{0,31}$"',
     r'r"^[a-zA-Z_][a-zA-Z0-9_.-]{0,31}$"', T + "test_cli_io_validation.py"),
    ("R1-stale-detector", T + "test_error_ratchet.py",
     "if found.get(key, 0) < n", "if found.get(key, 0) > n",
     T + "test_error_ratchet.py"),
    ("R2-bare-exit-branch", T + "test_error_ratchet.py",
     "else func.id if isinstance(func, ast.Name)",
     "else None if isinstance(func, ast.Name)", T + "test_error_ratchet.py"),
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
    """Production files this run would edit, repo-relative and unique."""
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
        return None  # not a git checkout; nothing to compare against
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", *_mutated_paths()],
        capture_output=True, text=True, cwd=REPO,
    )
    dirty = [ln for ln in status.stdout.splitlines() if ln.strip()]
    if not dirty:
        return None
    listing = "\n  ".join(dirty)
    return (
        "refusing to run: the production files this harness mutates have "
        "uncommitted changes.\n  " + listing +
        "\n\nCommit or stash them first - the harness must be the only "
        "thing editing these files."
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
