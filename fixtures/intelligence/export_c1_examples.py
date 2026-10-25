"""Export C1 PlanResult examples; run with backend Python, from any working directory.

These examples are derived from the normative synthetic contract inputs. They are
agent-3 integration artifacts, not replacements for contracts/examples or live results.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from repodoctor.contracts.api import AnalysisResponse
from repodoctor.contracts.domain import StaticAnalysis
from repodoctor.intelligence.service import IntelligenceServiceImpl

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parents[1] / "contracts" / "examples"


def load_scan(name: str) -> tuple[AnalysisResponse, StaticAnalysis]:
    response = AnalysisResponse.model_validate_json((EXAMPLES / name).read_text(encoding="utf-8"))
    scan = StaticAnalysis(
        repository=response.repository,
        source_mode=response.source_mode,
        facts=response.facts,
        findings=response.findings,
        evidence=response.evidence,
        coverage=response.coverage,
        selected_files=[],
    )
    return response, scan


async def main() -> None:
    service = IntelligenceServiceImpl()
    for source, output in [
        ("analysis_python.json", "plan_python_needs_input.json"),
        ("analysis_node.json", "plan_node.json"),
        ("analysis_needs_input.json", "plan_unknown.json"),
    ]:
        response, scan = load_scan(source)
        result = await service.build_plan(scan, response.target, use_ai=False)
        (HERE / output).write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
