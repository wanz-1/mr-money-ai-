"""Collaboration and workflow engine for Mr Money AI."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .models import utc_now


@dataclass
class Comment:
    id: str
    document_id: str
    author_id: str
    author_name: str
    body: str
    span_start: Optional[int] = None
    span_end: Optional[int] = None
    status: str = "open"
    created_at: str = field(default_factory=utc_now)
    resolved_at: Optional[str] = None
    replies: List["Comment"] = field(default_factory=list)
    parent_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "documentId": self.document_id,
            "authorId": self.author_id,
            "authorName": self.author_name,
            "body": self.body,
            "spanStart": self.span_start,
            "spanEnd": self.span_end,
            "status": self.status,
            "createdAt": self.created_at,
            "resolvedAt": self.resolved_at,
            "parentId": self.parent_id,
            "replies": [r.to_dict() for r in self.replies],
        }


@dataclass
class ApprovalStep:
    id: str
    document_id: str
    reviewer_id: str
    reviewer_name: str
    step_order: int
    status: str = "pending"
    decision_note: Optional[str] = None
    decided_at: Optional[str] = None
    created_at: str = field(default_factory=utc_now)
    due_date: Optional[str] = None
    sla_hours: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "documentId": self.document_id,
            "reviewerId": self.reviewer_id,
            "reviewerName": self.reviewer_name,
            "stepOrder": self.step_order,
            "status": self.status,
            "decisionNote": self.decision_note,
            "decidedAt": self.decided_at,
            "createdAt": self.created_at,
            "dueDate": self.due_date,
            "slaHours": self.sla_hours,
        }


@dataclass
class Workflow:
    id: str
    document_id: str
    name: str
    steps: List[ApprovalStep]
    status: str = "pending"
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "documentId": self.document_id,
            "name": self.name,
            "status": self.status,
            "steps": [s.to_dict() for s in self.steps],
            "createdAt": self.created_at,
        }


class CollaborationManager:
    def __init__(self) -> None:
        self._comments: Dict[str, List[Comment]] = {}
        self._workflows: Dict[str, Workflow] = {}

    def add_comment(
        self,
        document_id: str,
        author_id: str,
        author_name: str,
        body: str,
        span_start: Optional[int] = None,
        span_end: Optional[int] = None,
    ) -> Comment:
        comment = Comment(
            id=str(uuid.uuid4()),
            document_id=document_id,
            author_id=author_id,
            author_name=author_name,
            body=body,
            span_start=span_start,
            span_end=span_end,
        )
        self._comments.setdefault(document_id, []).append(comment)
        return comment

    def reply_to_comment(
        self,
        document_id: str,
        parent_comment_id: str,
        author_id: str,
        author_name: str,
        body: str,
    ) -> Optional[Comment]:
        for comment in self._comments.get(document_id, []):
            if comment.id == parent_comment_id:
                reply = Comment(
                    id=str(uuid.uuid4()),
                    document_id=document_id,
                    author_id=author_id,
                    author_name=author_name,
                    body=body,
                    parent_id=parent_comment_id,
                )
                comment.replies.append(reply)
                return reply
        return None

    def resolve_comment(self, comment_id: str) -> bool:
        for comments in self._comments.values():
            for comment in comments:
                if comment.id == comment_id:
                    comment.status = "resolved"
                    comment.resolved_at = utc_now()
                    return True
        return False

    def list_comments(self, document_id: str, status: Optional[str] = None) -> List[Comment]:
        comments = self._comments.get(document_id, [])
        if status:
            comments = [c for c in comments if c.status == status]
        return comments

    def create_workflow(
        self,
        document_id: str,
        name: str,
        reviewers: List[Dict[str, str]],
    ) -> Workflow:
        steps = []
        for i, reviewer in enumerate(reviewers):
            step = ApprovalStep(
                id=str(uuid.uuid4()),
                document_id=document_id,
                reviewer_id=reviewer.get("id", ""),
                reviewer_name=reviewer.get("name", "Reviewer"),
                step_order=i + 1,
            )
            steps.append(step)
        workflow = Workflow(
            id=str(uuid.uuid4()),
            document_id=document_id,
            name=name,
            steps=steps,
        )
        self._workflows[workflow.id] = workflow
        return workflow

    def decide_step(
        self,
        workflow_id: str,
        step_id: str,
        decision: str,
        reviewer_id: str,
        note: Optional[str] = None,
    ) -> Optional[Workflow]:
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return None
        for step in workflow.steps:
            if step.id == step_id and step.reviewer_id == reviewer_id:
                step.status = decision
                step.decision_note = note
                step.decided_at = utc_now()
                self._update_workflow_status(workflow)
                return workflow
        return None

    def _update_workflow_status(self, workflow: Workflow) -> None:
        statuses = [s.status for s in workflow.steps]
        if all(s == "approved" for s in statuses):
            workflow.status = "approved"
        elif any(s == "rejected" for s in statuses):
            workflow.status = "rejected"
        elif any(s == "changes_requested" for s in statuses):
            workflow.status = "changes_requested"
        elif any(s == "pending" for s in statuses):
            workflow.status = "in_progress"

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        return self._workflows.get(workflow_id)

    def get_document_workflow(self, document_id: str) -> Optional[Workflow]:
        for workflow in self._workflows.values():
            if workflow.document_id == document_id:
                return workflow
        return None


def create_default_workflow(document_id: str, reviewer_ids: List[Dict[str, str]]) -> Workflow:
    manager = CollaborationManager()
    return manager.create_workflow(document_id, "Standard Review", reviewer_ids)


SEQUENTIAL_WORKFLOW = "sequential"
PARALLEL_WORKFLOW = "parallel"

WORKFLOW_TEMPLATES = {
    "single_reviewer": {
        "name": "Single Reviewer",
        "steps": 1,
        "type": SEQUENTIAL_WORKFLOW,
    },
    "peer_review": {
        "name": "Peer Review",
        "steps": 2,
        "type": SEQUENTIAL_WORKFLOW,
    },
    "editorial_review": {
        "name": "Editorial Review",
        "steps": 3,
        "type": SEQUENTIAL_WORKFLOW,
    },
    "legal_review": {
        "name": "Legal Review",
        "steps": 2,
        "type": SEQUENTIAL_WORKFLOW,
    },
    "committee_approval": {
        "name": "Committee Approval",
        "steps": 5,
        "type": PARALLEL_WORKFLOW,
    },
}
