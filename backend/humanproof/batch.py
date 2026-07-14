"""Batch document processing for HumanProof AI."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .extractors import extract_document
from .models import Document, DocumentMetadata, ReviewReport, utc_now
from .orchestrator import review_document


@dataclass
class BatchJob:
    id: str
    status: str  # "pending", "running", "completed", "failed"
    total_documents: int
    completed_documents: int = 0
    failed_documents: int = 0
    results: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None

    @property
    def progress_percent(self) -> float:
        if self.total_documents == 0:
            return 0.0
        return round((self.completed_documents + self.failed_documents) / self.total_documents * 100, 1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "totalDocuments": self.total_documents,
            "completedDocuments": self.completed_documents,
            "failedDocuments": self.failed_documents,
            "progressPercent": self.progress_percent,
            "results": self.results,
            "createdAt": self.created_at,
            "startedAt": self.started_at,
            "completedAt": self.completed_at,
            "error": self.error,
        }


class BatchProcessor:
    def __init__(self, max_workers: int = 4) -> None:
        self._jobs: Dict[str, BatchJob] = {}
        self._max_workers = max_workers
        self._lock = threading.Lock()

    def create_job(self, documents: List[Tuple[str, bytes, str]]) -> BatchJob:
        job = BatchJob(
            id=str(uuid.uuid4()),
            status="pending",
            total_documents=len(documents),
        )
        self._jobs[job.id] = job
        thread = threading.Thread(target=self._process_job, args=(job, documents), daemon=True)
        thread.start()
        return job

    def get_job(self, job_id: str) -> Optional[BatchJob]:
        return self._jobs.get(job_id)

    def list_jobs(self, limit: int = 20) -> List[BatchJob]:
        jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    def _process_job(self, job: BatchJob, documents: List[Tuple[str, bytes, str]]) -> None:
        job.status = "running"
        job.started_at = utc_now()

        def process_one(item: Tuple[str, bytes, str]) -> Dict[str, Any]:
            filename, data, content_type = item
            try:
                document = extract_document(data, filename, content_type)
                report = review_document(document)
                return {
                    "filename": filename,
                    "status": "completed",
                    "reviewId": report.review_id,
                    "publicationReadiness": report.scores.get("publication_readiness", 0),
                    "findingCount": len(report.findings),
                    "summary": report.summary,
                }
            except Exception as exc:
                return {
                    "filename": filename,
                    "status": "failed",
                    "error": str(exc),
                }

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {executor.submit(process_one, doc): doc for doc in documents}
            for future in as_completed(futures):
                result = future.result()
                with self._lock:
                    job.results.append(result)
                    if result["status"] == "completed":
                        job.completed_documents += 1
                    else:
                        job.failed_documents += 1

        job.status = "completed"
        job.completed_at = utc_now()

    def get_aggregate_summary(self, job_id: str) -> Optional[Dict[str, Any]]:
        job = self._jobs.get(job_id)
        if not job or job.status != "completed":
            return None

        completed = [r for r in job.results if r["status"] == "completed"]
        if not completed:
            return {"message": "No completed reviews to summarize."}

        scores = [r["publicationReadiness"] for r in completed]
        avg_score = sum(scores) / len(scores) if scores else 0
        min_score = min(scores) if scores else 0
        max_score = max(scores) if scores else 0

        return {
            "totalDocuments": job.total_documents,
            "completedDocuments": job.completed_documents,
            "failedDocuments": job.failed_documents,
            "averageReadiness": round(avg_score, 1),
            "minReadiness": round(min_score, 1),
            "maxReadiness": round(max_score, 1),
            "documentsBelowThreshold": sum(1 for s in scores if s < 60),
        }
