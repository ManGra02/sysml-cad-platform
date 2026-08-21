"""Verifikations-Engine: Anforderung + Mapping + Messung -> Urteil."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from .extract import load
from .measure import load_part, measure
from .model import Requirement, Verdict

ROOT = Path(__file__).resolve().parents[2]
MAPPING = ROOT / "mapping" / "mapping.yaml"


def load_mapping(path: Path = MAPPING) -> dict[str, dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {m["requirement_id"]: m for m in data["mappings"]}


def run(project_id: str | None = None) -> list[Verdict]:
    requirements = load(project_id)
    mapping = load_mapping()
    verdicts: list[Verdict] = []

    for req in requirements:
        m = mapping.get(req.requirement_id)
        if m is None:
            print(f"[warn] kein Mapping fuer {req.requirement_id} -- uebersprungen")
            continue
        part, _ = load_part(m["cad_module"])
        measured = measure(part, m["method"], m.get("args"))
        verdicts.append(
            Verdict(
                requirement=req,
                measured=measured,
                passed=req.check(measured),
                method=f"{m['method']}({m.get('args', {})})",
            )
        )
    return verdicts


def report(verdicts: list[Verdict]) -> int:
    print(f"\n{'ID':<8} {'Property':<10} {'Gemessen':>14} {'Grenze':>14}  Status")
    print("-" * 68)
    for v in verdicts:
        status = "OK" if v.passed else "VERLETZT"
        print(
            f"{v.requirement.requirement_id:<8} {v.requirement.prop:<10} "
            f"{v.measured:>14.4g~P} {v.requirement.limit:>14.4g~P}  {status}"
        )
    failed = [v for v in verdicts if not v.passed]
    print("-" * 68)
    print(f"{len(verdicts) - len(failed)} erfuellt, {len(failed)} verletzt\n")
    for v in failed:
        print(
            f"  {v.requirement.requirement_id} verletzt: "
            f"{v.requirement.prop} = {v.measured:.4g~P} "
            f"{v.requirement.operator} {v.requirement.limit:.4g~P} ist falsch "
            f"(Quelle: {v.requirement.element_id}, Methode: {v.method})"
        )
    return 1 if failed else 0


def main() -> int:
    project_id = sys.argv[1] if len(sys.argv) > 1 else None
    return report(run(project_id))


if __name__ == "__main__":
    raise SystemExit(main())
