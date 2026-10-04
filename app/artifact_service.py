"""Explicit immutable Artifact admission, publication and relation records."""
import json
from pathlib import Path
from fastapi import HTTPException
from .db import Approval, Artifact, ArtifactPublication, ArtifactRelation, ArtifactReview, Run, TaskRun, TaskRunOutput, Work
from .workspace import ident, safe_read, sha
from .workspace import atomic_write, safe_child
from .storage import file_bytes
from .config import DATA_DIR


def artifact_bytes(db, artifact):
    work = db.get(Work, artifact.work_id)
    try:
        data = file_bytes(work, artifact)
    except (OSError, ValueError) as exc:
        artifact.availability = "MISSING"
        raise ValueError(f"INPUT_ARTIFACT_UNAVAILABLE: {artifact.id}") from exc
    if len(data) != artifact.size or sha(data) != artifact.sha256:
        artifact.availability = "MODIFIED"
        raise ValueError(f"INPUT_ARTIFACT_CHANGED: {artifact.id}")
    artifact.availability = "AVAILABLE"
    return data


def admit_artifact(db, artifact_id, consumer_work, *, verify=False, frozen=False):
    a = db.get(Artifact, artifact_id)
    if not a:
        raise ValueError(f"Artifact not found: {artifact_id}")
    run = db.get(Run, a.run_id)
    if not run:
        raise ValueError(f"Artifact has no associated Run: {artifact_id}")
    task = db.query(TaskRun).filter_by(run_id=a.run_id).first()
    if a.partial or (not frozen and a.availability != "AVAILABLE") or run.status != "COMPLETED" or (task and task.status != "COMPLETED"):
        raise ValueError(f"Artifact is not a confirmed output: {artifact_id}")
    if task and not db.query(TaskRunOutput).filter_by(task_run_id=task.id, artifact_id=a.id).first():
        raise ValueError(f"Artifact has no confirmed Task output slot: {artifact_id}")
    if task and not frozen:
        from .workflow_operations import gate
        checked = db.get(ArtifactReview, a.id)
        if gate(db, task) != "APPROVED" or (checked and checked.status in {"REJECTED", "REVISION_REQUESTED", "CANCELLED"}):
            raise ValueError(f"Artifact review has not admitted this output: {artifact_id}")
    if not frozen and a.work_id != consumer_work.id:
        publication = db.query(ArtifactPublication).filter_by(artifact_id=a.id, status="PUBLISHED").first()
        if not publication or not (publication.scope == "GLOBAL" or
            (publication.scope == "CATEGORY" and publication.category_id == consumer_work.category_id)):
            raise ValueError(f"Artifact is outside this Work's Library scope: {artifact_id}")
    if verify:
        artifact_bytes(db, a)
    return a


def input_relation(db, task, key, artifact):
    row = db.query(ArtifactRelation).filter_by(kind="INPUT", target_task_run_id=task.id, input_key=key).first()
    if row:
        if row.source_artifact_id != artifact.id or row.expected_sha256 != artifact.sha256:
            raise ValueError("Frozen input binding changed")
        return row
    row = ArtifactRelation(id=ident("rel"), kind="INPUT", source_artifact_id=artifact.id,
                           target_task_run_id=task.id, input_key=key, expected_sha256=artifact.sha256)
    db.add(row)
    return row


def artifact_edge(db, kind, source, target):
    if source == target:
        raise ValueError("Self lineage is not allowed")
    row = db.query(ArtifactRelation).filter_by(kind=kind, source_artifact_id=source, target_artifact_id=target).first()
    if not row:
        db.add(ArtifactRelation(id=ident("rel"), kind=kind, source_artifact_id=source, target_artifact_id=target))


def publish(db, artifact_id, scope):
    a = db.get(Artifact, artifact_id)
    if not a:
        raise HTTPException(404, "Artifact not found")
    review = db.get(ArtifactReview, a.id)
    if review and review.status != "APPROVED":
        raise HTTPException(409, "Approve the Artifact before publishing")
    work = db.get(Work, a.work_id)
    try:
        admit_artifact(db, a.id, work, verify=True)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    row = db.query(ArtifactPublication).filter_by(artifact_id=a.id).first()
    if not row:
        row = ArtifactPublication(id=ident("pub"), artifact_id=a.id, scope=scope)
        db.add(row)
    row.scope, row.category_id = scope, work.category_id if scope == "CATEGORY" else None
    if scope in {"CATEGORY", "GLOBAL"}:
        content = artifact_bytes(db, a)
        relative = f"shared/{'global' if scope == 'GLOBAL' else 'category/' + work.category_id}/{a.id}/{a.name}"
        destination = safe_child(DATA_DIR, relative)
        if destination.exists():
            if sha(safe_read(DATA_DIR, relative)) != a.sha256:
                raise HTTPException(409, "Shared copy changed; refusing to overwrite")
        else:
            atomic_write(destination, content)
        a.origin_path = a.origin_path or str(Path(a.location_root or work.path) / a.relative_path)
        a.location_type, a.location_root, a.relative_path = "SHARED", str(DATA_DIR), relative
    return row


def library(db, work, scope=None):
    result = []
    from .db import dump
    for p in db.query(ArtifactPublication).filter_by(status="PUBLISHED"):
        if scope and p.scope != scope:
            continue
        a = db.get(Artifact, p.artifact_id)
        if not a:
            # Legacy databases may contain a publication whose Artifact was
            # removed outside the application. It must not break Work loading.
            continue
        if p.scope == "GLOBAL" or (p.scope == "CATEGORY" and p.category_id == work.category_id) or (p.scope == "WORK" and a.work_id == work.id):
            try:
                admit_artifact(db, a.id, work)
            except ValueError:
                continue
            result.append({**dump(a), "publication": dump(p)})
    return result
