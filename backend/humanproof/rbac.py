"""Role-Based Access Control for HumanProof AI."""

from __future__ import annotations

from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Set


class Permission(str, Enum):
    READ = "read"
    WRITE = "write"
    REVIEW = "review"
    MANAGE_WORKSPACE = "manage_workspace"
    MANAGE_ORG = "manage_org"
    ADMIN = "admin"
    EXPORT_REPORTS = "export_reports"
    MANAGE_USERS = "manage_users"
    MANAGE_API_KEYS = "manage_api_keys"
    MANAGE_WEBHOOKS = "manage_webhooks"
    VIEW_AUDIT_LOGS = "view_audit_logs"
    MANAGE_STYLE_GUIDES = "manage_style_guides"
    MANAGE_KNOWLEDGE_BASE = "manage_knowledge_base"
    RUN_BATCH = "run_batch"
    MANAGE_WORKFLOWS = "manage_workflows"


class Role(str, Enum):
    VIEWER = "viewer"
    REVIEWER = "reviewer"
    EDITOR = "editor"
    ADMIN = "admin"
    ORG_ADMIN = "org_admin"


ROLE_PERMISSIONS: Dict[Role, FrozenSet[Permission]] = {
    Role.VIEWER: frozenset({
        Permission.READ,
    }),
    Role.REVIEWER: frozenset({
        Permission.READ,
        Permission.WRITE,
        Permission.REVIEW,
        Permission.EXPORT_REPORTS,
    }),
    Role.EDITOR: frozenset({
        Permission.READ,
        Permission.WRITE,
        Permission.REVIEW,
        Permission.EXPORT_REPORTS,
        Permission.MANAGE_WORKSPACE,
        Permission.MANAGE_WORKFLOWS,
        Permission.RUN_BATCH,
    }),
    Role.ADMIN: frozenset({
        Permission.READ,
        Permission.WRITE,
        Permission.REVIEW,
        Permission.EXPORT_REPORTS,
        Permission.MANAGE_WORKSPACE,
        Permission.MANAGE_WORKFLOWS,
        Permission.RUN_BATCH,
        Permission.MANAGE_USERS,
        Permission.MANAGE_API_KEYS,
        Permission.MANAGE_WEBHOOKS,
        Permission.VIEW_AUDIT_LOGS,
        Permission.MANAGE_STYLE_GUIDES,
        Permission.MANAGE_KNOWLEDGE_BASE,
    }),
    Role.ORG_ADMIN: frozenset({
        perm for perm in Permission
    }),
}


def get_permissions_for_role(role: Role) -> Set[Permission]:
    return set(ROLE_PERMISSIONS.get(role, set()))


def has_permission(user_permissions: List[str], required: Permission) -> bool:
    return required.value in user_permissions


def has_any_permission(user_permissions: List[str], *required: Permission) -> bool:
    return any(perm.value in user_permissions for perm in required)


def check_document_access(
    user_permissions: List[str],
    action: str,
    document_owner_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> bool:
    if action == "read":
        return has_permission(user_permissions, Permission.READ)
    if action == "write":
        if has_permission(user_permissions, Permission.WRITE):
            return True
        if document_owner_id and user_id and document_owner_id == user_id:
            return True
        return False
    if action == "review":
        return has_permission(user_permissions, Permission.REVIEW)
    if action == "delete":
        return has_permission(user_permissions, Permission.MANAGE_WORKSPACE) or has_permission(user_permissions, Permission.ADMIN)
    if action == "manage":
        return has_permission(user_permissions, Permission.MANAGE_WORKSPACE) or has_permission(user_permissions, Permission.ADMIN)
    return False


DEFAULT_ROLES_SETUP = [
    (Role.VIEWER, ["read"]),
    (Role.REVIEWER, ["read", "write", "review", "export_reports"]),
    (Role.EDITOR, ["read", "write", "review", "export_reports", "manage_workspace", "manage_workflows", "run_batch"]),
    (Role.ADMIN, [
        "read", "write", "review", "export_reports", "manage_workspace",
        "manage_workflows", "run_batch", "manage_users", "manage_api_keys",
        "manage_webhooks", "view_audit_logs", "manage_style_guides", "manage_knowledge_base",
    ]),
    (Role.ORG_ADMIN, [p.value for p in Permission]),
]
