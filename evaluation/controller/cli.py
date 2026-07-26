"""Single command-line owner for the canonical Frontier controller."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from . import host, reports, source_proof, specs, workspace
from .artifacts import (
    StateError,
    canonical_bytes,
    json_object,
    load_json,
)


def _path(value: str | None) -> Path | None:
    return None if value is None else Path(value).absolute()


def _request() -> dict:
    lines = [line for line in sys.stdin.buffer.read().splitlines() if line.strip()]
    if len(lines) != 1:
        raise ValueError("host stdin must contain exactly one JSON record")
    value = json_object(lines[0], "host stdin")
    host.validate_request(value)
    return value


def _emit(value: dict) -> None:
    print(canonical_bytes(value).decode("utf-8"), flush=True)


def _run_host(arguments: argparse.Namespace) -> int:
    request = _request()
    manifest = load_json(Path(arguments.host_manifest))
    if arguments.synthetic:
        records = host.pure_fake_records(request, manifest)
    elif request["envelope"]["request_kind"] == "execute_case":
        events, result = workspace.execute_codex(
            Path.cwd(),
            request,
            manifest,
            candidate=_path(arguments.candidate),
            prior=_path(arguments.prior),
            background_skills=tuple(map(Path, arguments.background)),
        )
        records = [*events, result]
    elif request["envelope"]["request_kind"] == "model_grade":
        if not arguments.grader_prompt or not arguments.grader_schema:
            raise ValueError(
                "model_grade requires --grader-prompt and --grader-schema",
            )
        records = [
            workspace.execute_model_grade(
                Path.cwd(),
                request,
                manifest,
                prompt_path=Path(arguments.grader_prompt),
                schema_path=Path(arguments.grader_schema),
            ),
        ]
    else:
        records = host.pure_fake_records(request, manifest)
    for record in records:
        _emit(record)
    return 0


def _decision(arguments: argparse.Namespace) -> int:
    result = reports.create_decision_contract(
        phase=arguments.phase,
        repo=Path(arguments.repo),
        candidate_plugin_root=Path(arguments.plugin),
        controller_manifest_path=Path(arguments.controller_manifest),
        request_manifest_path=Path(arguments.request_manifest),
        output=Path(arguments.output),
    )
    _emit(result)
    return 0


def _freeze_corpus(arguments: argparse.Namespace) -> int:
    result = source_proof.freeze_corpus(
        kind=arguments.kind,
        corpus_root=Path(arguments.root),
        manifest_path=Path(arguments.manifest),
        output=Path(arguments.output),
    )
    _emit(result)
    return 0


def _gate_contract(arguments: argparse.Namespace) -> int:
    _emit(specs.gate_contract(arguments.phase))
    return 0


def _check_p4_corpus(arguments: argparse.Namespace) -> int:
    corpus = workspace.load_p4_corpus(Path(arguments.manifest))
    _emit({"provider_requests": 0, "task_count": len(corpus["tasks"])})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="frontier-controller")
    commands = parser.add_subparsers(dest="command", required=True)
    gate = commands.add_parser("gate-contract")
    gate.add_argument("--phase", choices=("d0", "formal"), required=True)
    gate.set_defaults(handler=_gate_contract)

    corpus = commands.add_parser("check-p4-corpus")
    corpus.add_argument("manifest")
    corpus.set_defaults(handler=_check_p4_corpus)

    freeze = commands.add_parser("freeze-corpus")
    freeze.add_argument("--kind", choices=("formal", "p4"), required=True)
    freeze.add_argument("--root", required=True)
    freeze.add_argument("--manifest", required=True)
    freeze.add_argument("--output", required=True)
    freeze.set_defaults(handler=_freeze_corpus)

    decision = commands.add_parser("decision-contract")
    decision.add_argument("--phase", choices=("d0", "formal"), required=True)
    for name in (
        "repo",
        "plugin",
        "controller-manifest",
        "request-manifest",
        "output",
    ):
        decision.add_argument(f"--{name}", required=True)
    decision.set_defaults(handler=_decision)

    run_host = commands.add_parser("host")
    run_host.add_argument("--host-manifest", required=True)
    run_host.add_argument("--candidate")
    run_host.add_argument("--prior")
    run_host.add_argument("--background", action="append", default=[])
    run_host.add_argument("--grader-prompt")
    run_host.add_argument("--grader-schema")
    run_host.add_argument("--codex-bin")
    run_host.add_argument("--codex-bin-sha256")
    run_host.add_argument("--synthetic", action="store_true")
    run_host.set_defaults(handler=_run_host)
    return parser


def main(arguments: list[str] | None = None) -> int:
    parsed = build_parser().parse_args(arguments)
    try:
        return parsed.handler(parsed)
    except (
        StateError,
        ValueError,
        host.HostError,
        reports.ReportError,
        source_proof.ProofError,
        workspace.WorkspaceError,
    ) as exc:
        print(f"frontier-controller: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
