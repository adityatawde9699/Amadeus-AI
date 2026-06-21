"""
ReportBuilder — stage 5 of the research pipeline.

Pure rendering: turns a :class:`ResearchReport` / :class:`ResearchManifest`
into the three canonical output payloads. No I/O — the storage stage writes
them to AMASPACE.

Outputs:
  report.md              — human-readable, citation-driven markdown report
  sources.json           — structured, traceable source list
  research_manifest.json — machine-readable run manifest
"""

from __future__ import annotations

import json

from src.research.models import ResearchManifest, ResearchReport
from src.research.validator import SourceValidator


class ReportBuilder:
    def build_markdown(self, report: ResearchReport) -> str:
        lines: list[str] = [f"# Research Report: {report.topic}", ""]
        lines.append(f"*Generated: {report.generated_at.isoformat()}*")
        lines.append("")

        lines += self._section("Executive Summary", report.executive_summary)
        lines += self._bullets("Key Findings", report.key_findings)
        lines += self._section("Detailed Analysis", report.detailed_analysis)
        lines += self._bullets("Risks", report.risks)
        lines += self._bullets("Open Questions", report.open_questions)
        lines += self._bullets("Future Directions", report.future_directions)

        if report.plan and report.plan.subtopics:
            lines.append("## Research Plan")
            lines.append("")
            for st in report.plan.subtopics:
                lines.append(f"### {st.title}")
                for q in st.questions:
                    lines.append(f"- {q.text}")
                lines.append("")

        if report.sources:
            lines.append("## Sources")
            lines.append("")
            for cite in SourceValidator.citations(report.sources):
                lines.append(cite)
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    def build_sources_json(self, report: ResearchReport) -> str:
        payload = {
            "topic": report.topic,
            "count": len(report.sources),
            "sources": [s.to_dict() for s in report.sources],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def build_manifest_json(self, manifest: ResearchManifest) -> str:
        return json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    @staticmethod
    def _section(title: str, body: str) -> list[str]:
        if not body:
            return []
        return [f"## {title}", "", body, ""]

    @staticmethod
    def _bullets(title: str, items: list[str]) -> list[str]:
        if not items:
            return []
        out = [f"## {title}", ""]
        out.extend(f"- {item}" for item in items)
        out.append("")
        return out
