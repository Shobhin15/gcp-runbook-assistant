"""Read-only tools the triage agent may call.

search_runbooks works offline. The other two read from Google Cloud and need
the runtime service account to hold roles/logging.viewer and roles/run.viewer
(see terraform/main.tf). Nothing here can change a resource.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from app import rag
from app.agent import Param, Tool, check_service


def _allowed_services() -> set[str] | None:
    raw = os.getenv("TRIAGE_SERVICES", "").strip()
    return {s.strip().lower() for s in raw.split(",") if s.strip()} or None


def runbook_tool(index: rag.RunbookIndex) -> Tool:
    def search_runbooks(query: str) -> dict:
        hits = index.search(query, k=3)
        return {
            "runbooks": sorted({c.source for c, _ in hits}),
            "excerpts": [{"runbook": c.source, "text": c.text, "score": round(s, 3)} for c, s in hits],
        }

    return Tool(
        name="search_runbooks",
        description="Search the team's on-call runbooks. Always check here before suggesting a fix.",
        params={"query": Param("string", "What to look up, e.g. 'pod CrashLoopBackOff OOMKilled'")},
        fn=search_runbooks,
    )


def error_logs_tool(project: str) -> Tool:
    def recent_error_logs(service: str, minutes: int = 30) -> dict:
        from google.cloud import logging as cloud_logging  # lazy: only needed on Google Cloud

        service = check_service(service, _allowed_services())
        minutes = max(5, min(int(minutes), 120))
        since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
        log_filter = (
            f'resource.type="cloud_run_revision" AND resource.labels.service_name="{service}" '
            f'AND severity>=ERROR AND timestamp>="{since}"'
        )
        client = cloud_logging.Client(project=project)
        entries = []
        for entry in client.list_entries(filter_=log_filter, order_by=cloud_logging.DESCENDING, max_results=20):
            payload = entry.payload if isinstance(entry.payload, str) else str(entry.payload)
            entries.append({"time": str(entry.timestamp), "severity": entry.severity, "message": payload[:300]})
        return {"service": service, "minutes": minutes, "error_count": len(entries), "entries": entries}

    return Tool(
        name="recent_error_logs",
        description="Read the most recent ERROR-level log lines for a Cloud Run service (max 20).",
        params={
            "service": Param("string", "Cloud Run service name"),
            "minutes": Param("integer", "How far back to look, 5 to 120 (default 30)", required=False),
        },
        fn=recent_error_logs,
    )


def service_status_tool(project: str, location: str) -> Tool:
    def cloud_run_status(service: str) -> dict:
        from google.cloud import run_v2  # lazy: only needed on Google Cloud

        service = check_service(service, _allowed_services())
        svc = run_v2.ServicesClient().get_service(
            name=f"projects/{project}/locations/{location}/services/{service}"
        )
        return {
            "service": service,
            "ready": svc.terminal_condition.state.name,
            "ready_message": svc.terminal_condition.message,
            "latest_ready_revision": svc.latest_ready_revision.split("/")[-1],
            "latest_created_revision": svc.latest_created_revision.split("/")[-1],
            "traffic": [
                {"revision": t.revision.split("/")[-1], "percent": t.percent} for t in svc.traffic_statuses
            ],
        }

    return Tool(
        name="cloud_run_status",
        description=(
            "Get a Cloud Run service's health: readiness, latest ready vs latest created revision, "
            "and traffic split. A newer created revision that is not ready often means a failed deploy."
        ),
        params={"service": Param("string", "Cloud Run service name")},
        fn=cloud_run_status,
    )


def default_tools(index: rag.RunbookIndex, project: str, location: str) -> list:
    return [runbook_tool(index), error_logs_tool(project), service_status_tool(project, location)]
