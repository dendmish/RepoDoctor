"""Regenerate StaticAnalysis handoff examples from B1 snapshots without network/AI."""

from __future__ import annotations

import asyncio
import json

from repodoctor.config import PROJECT_ROOT
from repodoctor.contracts.api import AnalysisRequest
from repodoctor.repository.source import FixtureRepositorySource
from repodoctor.scanners.analyzer import RepositoryAnalyzer


async def main() -> None:
    library = PROJECT_ROOT / "fixtures" / "repositories"
    index = json.loads((library / "index.json").read_text(encoding="utf-8"))
    source, analyzer = FixtureRepositorySource(), RepositoryAnalyzer()
    for entry in index["repositories"]:
        request = AnalysisRequest.model_validate(
            {
                "repo_url": entry["url"],
                "target": {"os": "linux", "shell": "bash"},
                "use_ai": False,
            }
        )
        scan = analyzer.analyze(await source.fetch(request))
        destination = library / entry["id"] / "scan.json"
        destination.write_text(scan.model_dump_json(indent=2) + "\n", encoding="utf-8")
        print(entry["id"], len(scan.evidence), "evidence", len(scan.findings), "findings")


if __name__ == "__main__":
    asyncio.run(main())
