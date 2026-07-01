from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.workspace import Workspace
from app.models.playground_user import WorkspaceExternalUser
from app.models.agent import AgentTask
from app.models.user import User
from app.routers.deps import get_current_user
from app.services.audit import create_log
from datetime import datetime
import json

router = APIRouter()

WORKSPACE_FIELDS = {
    "name",
    "description",
    "playground_workspace_id",
    "playground_url",
    "add_data_url",
    "embedding_model",
    "data_languages",
    "owner_user_id",
    "status",
    "created_via",
}

EXTERNAL_USER_FIELDS = {"name", "email", "user_identifier", "area", "notes", "status"}


def external_user_payload(data: dict) -> dict:
    data = dict(data or {})
    if data.get("network_id") and not data.get("user_identifier"):
        data["user_identifier"] = data.get("network_id")
    return {key: value for key, value in data.items() if key in EXTERNAL_USER_FIELDS}


def normalize_playground_data_languages(value) -> list[str]:
    languages = []
    for item in value or []:
        language = str(item).strip()
        if language and language not in languages:
            languages.append(language)
    return languages

def workspace_payload(data: dict) -> dict:
    clean = {key: value for key, value in (data or {}).items() if key in WORKSPACE_FIELDS}
    for key, value in list(clean.items()):
        if value == "":
            clean[key] = None
        if key == "data_languages" and isinstance(value, list):
            clean[key] = json.dumps(value, ensure_ascii=False)
    return clean

def workspace_out(workspace: Workspace, db: Session = None) -> dict:
    try:
        data_languages = json.loads(workspace.data_languages) if workspace.data_languages else []
    except Exception:
        data_languages = workspace.data_languages or []
    
    files_count = 0
    errors_count = 0
    last_upload_at = None
    if db is not None:
        from app.models.file import WorkspaceFile
        from app.models.automation import Automation
        
        automation_ids = [a.id for a in db.query(Automation).filter(
            Automation.workspace_id == workspace.id,
            Automation.is_deleted == False
        ).all()]
        
        file_query_filter = (WorkspaceFile.workspace_id == workspace.id)
        if automation_ids:
            file_query_filter = file_query_filter | (WorkspaceFile.automation_id.in_(automation_ids))
            
        files_count = db.query(WorkspaceFile).filter(
            file_query_filter,
            WorkspaceFile.is_deleted == False
        ).count()
        
        errors_count = db.query(WorkspaceFile).filter(
            file_query_filter,
            WorkspaceFile.is_deleted == False,
            WorkspaceFile.status.in_(["error", "failed"])
        ).count()
        
        last_file = db.query(WorkspaceFile).filter(
            file_query_filter,
            WorkspaceFile.is_deleted == False,
            WorkspaceFile.uploaded_at.isnot(None)
        ).order_by(WorkspaceFile.uploaded_at.desc()).first()
        
        if last_file:
            from app.core.timezone import sao_paulo_utc_iso
            last_upload_at = sao_paulo_utc_iso(last_file.uploaded_at)

    return {
        "id": workspace.id,
        "name": workspace.name,
        "description": workspace.description,
        "playground_workspace_id": workspace.playground_workspace_id,
        "playground_url": workspace.playground_url,
        "add_data_url": workspace.add_data_url,
        "embedding_model": workspace.embedding_model,
        "data_languages": data_languages,
        "owner_user_id": workspace.owner_user_id,
        "status": workspace.status,
        "created_via": workspace.created_via,
        "is_deleted": workspace.is_deleted,
        "deleted_at": workspace.deleted_at,
        "archived_at": workspace.archived_at,
        "created_at": workspace.created_at,
        "updated_at": workspace.updated_at,
        "files_count": files_count,
        "errors_count": errors_count,
        "last_upload_at": last_upload_at,
    }


@router.get("")
def list_workspaces(db: Session = Depends(get_db)):
    return [workspace_out(ws, db) for ws in db.query(Workspace).filter(Workspace.is_deleted == False).all()]

@router.get("/external-users")
def list_external_users(db: Session = Depends(get_db)):
    return db.query(WorkspaceExternalUser).filter(WorkspaceExternalUser.is_deleted == False).all()

@router.post("/external-users")
def create_external_user(data: dict, db: Session = Depends(get_db)):
    u = WorkspaceExternalUser(**external_user_payload(data))
    db.add(u)
    db.commit()
    db.refresh(u)
    return u

@router.put("/external-users/{id}")
def update_external_user(id: int, data: dict, db: Session = Depends(get_db)):
    u = db.query(WorkspaceExternalUser).filter(WorkspaceExternalUser.id == id, WorkspaceExternalUser.is_deleted == False).first()
    if not u: raise HTTPException(404)
    for k, v in external_user_payload(data).items():
        setattr(u, k, v)
    db.commit()
    return u

@router.delete("/external-users/{id}")
def delete_external_user(id: int, db: Session = Depends(get_db)):
    u = db.query(WorkspaceExternalUser).filter(WorkspaceExternalUser.id == id, WorkspaceExternalUser.is_deleted == False).first()
    if not u: raise HTTPException(404)
    u.is_deleted = True
    u.deleted_at = datetime.utcnow()
    db.commit()
    return {"status": "deleted"}

@router.post("/external-users/{id}/archive")
def archive_external_user(id: int, db: Session = Depends(get_db)):
    u = db.query(WorkspaceExternalUser).filter(WorkspaceExternalUser.id == id, WorkspaceExternalUser.is_deleted == False).first()
    if not u: raise HTTPException(404)
    u.status = "archived"
    u.archived_at = datetime.utcnow()
    db.commit()
    return {"status": "archived"}

@router.post("/external-users/{id}/send-to-workspace")
@router.post("/external-users/{id}/send")
def send_external_user(
    id: int,
    data: dict = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    u = db.query(WorkspaceExternalUser).filter(WorkspaceExternalUser.id == id, WorkspaceExternalUser.is_deleted == False).first()
    if not u: raise HTTPException(404)
    data = data or {}
    workspace = None
    workspace_id = data.get("workspace_id")
    if workspace_id:
        workspace = db.query(Workspace).filter(Workspace.id == int(workspace_id), Workspace.is_deleted == False).first()
    payload = {
        **data,
        "external_user_id": u.id,
        "external_user_name": u.name,
        "external_user_email": u.email,
        "user_identifier": u.user_identifier,
        "network_id": u.user_identifier,
        "workspace_id": workspace.id if workspace else data.get("workspace_id"),
        "workspace_name": workspace.name if workspace else data.get("workspace_name"),
        "user_id": current_user.id,
    }
    task = AgentTask(
        task_type="add_playground_user_to_workspace",
        status="pending",
        payload_json=json.dumps(payload, ensure_ascii=False),
        created_by_id=current_user.id,
    )
    db.add(task)
    db.commit()
    create_log(db, "info", "Requested add user to playground", "external_user", id)
    return {"status": "task_created", "task_id": task.id}

@router.post("")
def create_workspace(data: dict, db: Session = Depends(get_db)):
    clean = workspace_payload(data)
    if not clean.get("name"):
        raise HTTPException(422, "Workspace name is required")
    ws = Workspace(**clean)
    db.add(ws)
    db.commit()
    db.refresh(ws)
    create_log(db, "info", f"Workspace created: {ws.name}", "workspace", ws.id)
    return workspace_out(ws, db)


@router.get("/{id}")
def get_workspace(id: int, db: Session = Depends(get_db)):
    ws = db.query(Workspace).filter(Workspace.id == id, Workspace.is_deleted == False).first()
    if not ws: raise HTTPException(404)
    return workspace_out(ws, db)


@router.put("/{id}")
def update_workspace(id: int, data: dict, db: Session = Depends(get_db)):
    ws = db.query(Workspace).filter(Workspace.id == id, Workspace.is_deleted == False).first()
    if not ws: raise HTTPException(404)
    for k, v in workspace_payload(data).items():
        setattr(ws, k, v)
    db.commit()
    db.refresh(ws)
    create_log(db, "info", "Workspace edited", "workspace", ws.id)
    return workspace_out(ws, db)

@router.delete("/{id}")
def delete_workspace(id: int, db: Session = Depends(get_db)):
    ws = db.query(Workspace).filter(Workspace.id == id, Workspace.is_deleted == False).first()
    if not ws: raise HTTPException(404)
    ws.is_deleted = True
    ws.deleted_at = datetime.utcnow()
    db.commit()
    create_log(db, "warning", "Workspace deleted", "workspace", ws.id)
    return {"status": "deleted"}

@router.post("/{id}/actions/{action}")
def workspace_action(id: int, action: str, db: Session = Depends(get_db)):
    ws = db.query(Workspace).filter(Workspace.id == id, Workspace.is_deleted == False).first()
    if not ws: raise HTTPException(404)
    if action == "delete":
        ws.is_deleted = True
        ws.deleted_at = datetime.utcnow()
    elif action == "archive":
        ws.status = "archived"
        ws.archived_at = datetime.utcnow()
    elif action in ["start", "stop", "pause", "resume"]:
        ws.status = "active" if action in ["start", "resume"] else "paused"
    else:
        raise HTTPException(400, "Invalid action")
    db.commit()
    create_log(db, "info", f"Workspace action {action}", "workspace", ws.id)
    return {"status": "action executed", "action": action}

@router.post("/playground-request")
def playground_request(data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    payload = data or {}
    payload["data_languages"] = normalize_playground_data_languages(payload.get("data_languages"))
    payload["user_id"] = current_user.id
    task = AgentTask(
        task_type="create_playground_workspace",
        status="pending",
        payload_json=json.dumps(payload, ensure_ascii=False),
        created_by_id=current_user.id,
    )
    db.add(task)
    db.commit()
    create_log(db, "info", "Requested playground workspace", "workspace", None)
    return {"status": "task_created"}
