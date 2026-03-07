"""
api.py  —  Atlassian AI Agent API v3
─────────────────────────────────────
Çalıştırmak için:
  cp .env.example .env   # doldur
  uvicorn api:app --host 0.0.0.0 --port 8000
"""

import os
os.environ["OPENAI_API_KEY"]  = "dummy"
os.environ["OPENAI_BASE_URL"] = os.getenv("VLLM_URL", "http://sinerjicuda02:8010/v1")
os.environ["OPENAI_API_BASE"] = os.getenv("VLLM_URL", "http://sinerjicuda02:8010/v1")
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"

from typing import Optional
from datetime import datetime as dt

from fastapi import FastAPI, HTTPException, Security, Depends
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from jira import JIRA
from atlassian import Confluence
from crewai import LLM

from agent import run_agent

# ── Ayarlar ───────────────────────────────────────────────────────────────────
API_KEY           = os.getenv("API_KEY",           "your-secret-key")
JIRA_SERVER       = os.getenv("JIRA_SERVER",       "https://jira.sbm.org.tr")
JIRA_EMAIL        = os.getenv("JIRA_EMAIL",        "")
JIRA_TOKEN        = os.getenv("JIRA_TOKEN",        "")
CONFLUENCE_SERVER = os.getenv("CONFLUENCE_SERVER", "https://confluence.sbm.org.tr")
CONFLUENCE_EMAIL  = os.getenv("CONFLUENCE_EMAIL",  "")
CONFLUENCE_TOKEN  = os.getenv("CONFLUENCE_TOKEN",  "")
MODEL_NAME        = os.getenv("MODEL_NAME",        "Qwen/Qwen3-VL-8B-Thinking")

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Atlassian AI Agent API",
    version="3.0.0",
    description=(
        "Jira + Confluence yönetim API'si.\n\n"
        "**Jira**: issue CRUD, batch, worklog, attachment, link, epic, "
        "versiyon, board, sprint, changelog\n\n"
        "**Confluence**: sayfa CRUD, arama, yorum, etiket, attachment, Jira bağlantısı\n\n"
        "**Agent** (`/chat`): Serbest metin — tüm tool'ları kullanır"
    ),
)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

def verify_api_key(key: str = Security(api_key_header)) -> str:
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Geçersiz API key")
    return key

def get_jira() -> JIRA:
    return JIRA(server=JIRA_SERVER, basic_auth=(JIRA_EMAIL, JIRA_TOKEN))

def get_confluence() -> Confluence:
    return Confluence(url=CONFLUENCE_SERVER, username=CONFLUENCE_EMAIL, password=CONFLUENCE_TOKEN)

def get_llm() -> LLM:
    return LLM(model=MODEL_NAME, api_key="dummy", temperature=0.3, max_tokens=4096)


# ── Ortak modeller ─────────────────────────────────────────────────────────────
class Msg(BaseModel):
    message: str


# ══════════════════════════════════════════════════════════════════════════════
# GENEL
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health", tags=["Genel"])
def health():
    return {"status": "ok", "version": "3.0.0"}


# ══════════════════════════════════════════════════════════════════════════════
# JIRA — SORGULAMA
# ══════════════════════════════════════════════════════════════════════════════

class QueryRequest(BaseModel):
    jql: str
    max_results: int = 10

@app.post("/jira/search", tags=["Jira - Sorgulama"])
def jira_search(req: QueryRequest, _: str = Depends(verify_api_key)):
    """JQL ile issue sorgula."""
    jira = get_jira()
    issues = jira.search_issues(req.jql, maxResults=req.max_results)
    return {"issues": [
        {"key": i.key, "summary": i.fields.summary, "status": i.fields.status.name,
         "assignee": getattr(i.fields.assignee, "displayName", "—"),
         "priority": getattr(i.fields.priority, "name", "—")}
        for i in issues], "total": len(issues)}


@app.get("/jira/issue/{issue_key}", tags=["Jira - Sorgulama"])
def jira_get_issue(issue_key: str, _: str = Depends(verify_api_key)):
    """Issue detaylarını getir."""
    jira  = get_jira()
    i     = jira.issue(issue_key)
    return {
        "key": i.key, "summary": i.fields.summary,
        "type": i.fields.issuetype.name, "status": i.fields.status.name,
        "priority": getattr(i.fields.priority, "name", "—"),
        "assignee": getattr(i.fields.assignee, "displayName", "—"),
        "reporter": getattr(i.fields.reporter, "displayName", "—"),
        "project": i.fields.project.key,
        "labels": i.fields.labels,
        "components": [c.name for c in i.fields.components],
        "subtasks": [s.key for s in i.fields.subtasks],
        "created": str(i.fields.created)[:10],
        "updated": str(i.fields.updated)[:10],
        "description": str(i.fields.description or "")[:500],
        "url": i.permalink(),
    }


@app.get("/jira/projects", tags=["Jira - Sorgulama"])
def jira_get_projects(_: str = Depends(verify_api_key)):
    """Tüm projeleri listele."""
    projects = get_jira().projects()
    return [{"key": p.key, "name": p.name,
             "type": getattr(p, "projectTypeKey", "—")} for p in projects]


@app.get("/jira/project/{project_key}/issues", tags=["Jira - Sorgulama"])
def jira_get_project_issues(project_key: str, status: Optional[str] = None,
                             max_results: int = 20, _: str = Depends(verify_api_key)):
    """Proje issue'larını listele."""
    jira = get_jira()
    jql  = f"project={project_key}"
    if status: jql += f" AND status='{status}'"
    jql += " ORDER BY created DESC"
    issues = jira.search_issues(jql, maxResults=max_results)
    return {"issues": [
        {"key": i.key, "summary": i.fields.summary, "status": i.fields.status.name,
         "assignee": getattr(i.fields.assignee, "displayName", "—")}
        for i in issues]}


@app.get("/jira/issue/{issue_key}/transitions", tags=["Jira - Sorgulama"])
def jira_get_transitions(issue_key: str, _: str = Depends(verify_api_key)):
    """Mevcut durum geçişlerini listele."""
    transitions = get_jira().transitions(issue_key)
    return [{"id": t["id"], "name": t["name"]} for t in transitions]


@app.get("/jira/users", tags=["Jira - Sorgulama"])
def jira_search_users(query: str, _: str = Depends(verify_api_key)):
    """Kullanıcı ara."""
    users = get_jira().search_users(query)
    return [{"displayName": u.displayName,
             "email": getattr(u, "emailAddress", "—"),
             "name": u.name, "active": u.active}
            for u in users]


@app.get("/jira/issue/{issue_key}/changelog", tags=["Jira - Sorgulama"])
def jira_get_changelog(issue_key: str, max_results: int = 20,
                        _: str = Depends(verify_api_key)):
    """Issue değişiklik geçmişi."""
    issue     = get_jira().issue(issue_key, expand="changelog")
    histories = issue.changelog.histories[:max_results]
    rows = []
    for h in histories:
        for item in h.items:
            rows.append({"date": str(h.created)[:16], "author": h.author.displayName,
                         "field": item.field, "from": item.fromString, "to": item.toString})
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# JIRA — OLUŞTURMA / GÜNCELLEME / SİLME
# ══════════════════════════════════════════════════════════════════════════════

class CreateIssueReq(BaseModel):
    project_key: str
    summary: str
    description: str = ""
    issue_type: str = "Story"
    assignee_email: Optional[str] = None
    priority: Optional[str] = None
    labels: Optional[list[str]] = None
    components: Optional[list[str]] = None
    parent_key: Optional[str] = None

@app.post("/jira/issue", tags=["Jira - CRUD"])
def jira_create_issue(req: CreateIssueReq, _: str = Depends(verify_api_key)):
    """Yeni issue oluştur."""
    jira = get_jira()
    fields: dict = {"project": {"key": req.project_key}, "summary": req.summary,
        "description": req.description, "issuetype": {"name": req.issue_type}}
    if req.assignee_email: fields["assignee"]   = {"emailAddress": req.assignee_email}
    if req.priority:       fields["priority"]   = {"name": req.priority}
    if req.labels:         fields["labels"]     = req.labels
    if req.components:     fields["components"] = [{"name": c} for c in req.components]
    if req.parent_key:     fields["parent"]     = {"key": req.parent_key}
    issue = jira.create_issue(fields=fields)
    return {"key": issue.key, "url": issue.permalink()}


class BatchCreateReq(BaseModel):
    issues: list[CreateIssueReq]

@app.post("/jira/issues/batch", tags=["Jira - CRUD"])
def jira_batch_create(req: BatchCreateReq, _: str = Depends(verify_api_key)):
    """Birden fazla issue oluştur."""
    jira    = get_jira()
    results = []
    for item in req.issues:
        try:
            fields: dict = {"project": {"key": item.project_key}, "summary": item.summary,
                "description": item.description, "issuetype": {"name": item.issue_type}}
            if item.assignee_email: fields["assignee"]   = {"emailAddress": item.assignee_email}
            if item.priority:       fields["priority"]   = {"name": item.priority}
            if item.labels:         fields["labels"]     = item.labels
            if item.components:     fields["components"] = [{"name": c} for c in item.components]
            issue = jira.create_issue(fields=fields)
            results.append({"key": issue.key, "summary": item.summary, "status": "ok"})
        except Exception as e:
            results.append({"key": None, "summary": item.summary, "status": f"hata: {e}"})
    return {"results": results, "total": len(results)}


class UpdateIssueReq(BaseModel):
    summary: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    assignee_email: Optional[str] = None
    priority: Optional[str] = None
    project_key: Optional[str] = None
    labels: Optional[list[str]] = None

@app.put("/jira/issue/{issue_key}", response_model=Msg, tags=["Jira - CRUD"])
def jira_update_issue(issue_key: str, req: UpdateIssueReq, _: str = Depends(verify_api_key)):
    """Issue güncelle."""
    jira  = get_jira()
    issue = jira.issue(issue_key)
    upd: dict = {}
    if req.summary:        upd["summary"]     = req.summary
    if req.description:    upd["description"] = req.description
    if req.assignee_email: upd["assignee"]    = {"emailAddress": req.assignee_email}
    if req.priority:       upd["priority"]    = {"name": req.priority}
    if req.project_key:    upd["project"]     = {"key": req.project_key}
    if req.labels is not None: upd["labels"]  = req.labels
    if upd: issue.update(fields=upd)
    if req.status:
        transitions = jira.transitions(issue)
        match = next((t for t in transitions if t["name"].lower() == req.status.lower()), None)
        if not match:
            raise HTTPException(400, f"'{req.status}' bulunamadı. Mevcut: {[t['name'] for t in transitions]}")
        jira.transition_issue(issue, match["id"])
    return Msg(message=f"{issue_key} güncellendi.")


@app.post("/jira/issue/{issue_key}/transition", response_model=Msg, tags=["Jira - CRUD"])
def jira_transition(issue_key: str, transition_name: str, _: str = Depends(verify_api_key)):
    """Issue durumunu değiştir."""
    jira        = get_jira()
    transitions = jira.transitions(issue_key)
    match = next((t for t in transitions if t["name"].lower() == transition_name.lower()), None)
    if not match:
        raise HTTPException(400, f"'{transition_name}' bulunamadı. Mevcut: {[t['name'] for t in transitions]}")
    jira.transition_issue(issue_key, match["id"])
    return Msg(message=f"{issue_key} → '{transition_name}' yapıldı.")


@app.delete("/jira/issue/{issue_key}", response_model=Msg, tags=["Jira - CRUD"])
def jira_delete_issue(issue_key: str, _: str = Depends(verify_api_key)):
    """Issue sil. GERİ ALINAMAZ!"""
    get_jira().issue(issue_key).delete()
    return Msg(message=f"{issue_key} silindi.")


# ── Yorum ─────────────────────────────────────────────────────────────────────

class CommentReq(BaseModel):
    comment: str

@app.post("/jira/issue/{issue_key}/comment", response_model=Msg, tags=["Jira - Yorum & Worklog"])
def jira_add_comment(issue_key: str, req: CommentReq, _: str = Depends(verify_api_key)):
    get_jira().add_comment(issue_key, req.comment)
    return Msg(message=f"{issue_key} issue'suna yorum eklendi.")


# ── Worklog ───────────────────────────────────────────────────────────────────

class WorklogReq(BaseModel):
    time_spent: str
    comment: Optional[str] = None
    started: Optional[str] = None

@app.post("/jira/issue/{issue_key}/worklog", response_model=Msg, tags=["Jira - Yorum & Worklog"])
def jira_add_worklog(issue_key: str, req: WorklogReq, _: str = Depends(verify_api_key)):
    """Worklog ekle. time_spent: '2h 30m', '1d', '4h'"""
    kwargs: dict = {}
    if req.comment: kwargs["comment"] = req.comment
    if req.started: kwargs["started"] = dt.strptime(req.started, "%Y-%m-%d %H:%M")
    get_jira().add_worklog(issue_key, timeSpent=req.time_spent, **kwargs)
    return Msg(message=f"{issue_key} — {req.time_spent} worklog eklendi.")


@app.get("/jira/issue/{issue_key}/worklog", tags=["Jira - Yorum & Worklog"])
def jira_get_worklog(issue_key: str, _: str = Depends(verify_api_key)):
    worklogs = get_jira().worklogs(issue_key)
    return [{"author": w.author.displayName, "time_spent": w.timeSpent,
             "started": w.started[:10], "comment": getattr(w, "comment", "")}
            for w in worklogs]


# ── Attachment ────────────────────────────────────────────────────────────────

@app.get("/jira/issue/{issue_key}/attachments", tags=["Jira - Attachment"])
def jira_list_attachments(issue_key: str, _: str = Depends(verify_api_key)):
    issue = get_jira().issue(issue_key)
    return [{"filename": a.filename, "size": a.size, "created": a.created[:10],
             "author": a.author.displayName, "url": a.content}
            for a in issue.fields.attachment]


# ── Issue Link ────────────────────────────────────────────────────────────────

@app.get("/jira/link-types", tags=["Jira - Link & Epic"])
def jira_link_types(_: str = Depends(verify_api_key)):
    types = get_jira().issue_link_types()
    return [{"name": lt.name, "inward": lt.inward, "outward": lt.outward} for lt in types]


class IssueLinkReq(BaseModel):
    link_type: str
    inward_issue: str
    outward_issue: str

@app.post("/jira/issue-link", response_model=Msg, tags=["Jira - Link & Epic"])
def jira_create_link(req: IssueLinkReq, _: str = Depends(verify_api_key)):
    get_jira().create_issue_link(
        type=req.link_type,
        inwardIssue=req.inward_issue,
        outwardIssue=req.outward_issue,
    )
    return Msg(message=f"{req.inward_issue} ↔ {req.outward_issue} ({req.link_type}) bağlandı.")


@app.delete("/jira/issue-link/{link_id}", response_model=Msg, tags=["Jira - Link & Epic"])
def jira_delete_link(link_id: str, _: str = Depends(verify_api_key)):
    get_jira().delete_issue_link(link_id)
    return Msg(message=f"Link {link_id} silindi.")


class EpicReq(BaseModel):
    issue_key: str
    epic_key: str

@app.post("/jira/epic-link", response_model=Msg, tags=["Jira - Link & Epic"])
def jira_link_epic(req: EpicReq, _: str = Depends(verify_api_key)):
    issue = get_jira().issue(req.issue_key)
    for field_id in ["customfield_10014", "customfield_10008"]:
        try:
            issue.update(fields={field_id: req.epic_key})
            return Msg(message=f"{req.issue_key} → Epic {req.epic_key}'e bağlandı.")
        except Exception:
            continue
    raise HTTPException(400, "Epic link alanı bulunamadı.")


# ── Versiyon ──────────────────────────────────────────────────────────────────

@app.get("/jira/project/{project_key}/versions", tags=["Jira - Versiyon"])
def jira_get_versions(project_key: str, _: str = Depends(verify_api_key)):
    versions = get_jira().project_versions(project_key)
    return [{"id": v.id, "name": v.name,
             "released": getattr(v, "released", False),
             "release_date": getattr(v, "releaseDate", "—")}
            for v in versions]


class VersionReq(BaseModel):
    name: str
    description: Optional[str] = None
    release_date: Optional[str] = None
    released: bool = False

@app.post("/jira/project/{project_key}/version", tags=["Jira - Versiyon"])
def jira_create_version(project_key: str, req: VersionReq, _: str = Depends(verify_api_key)):
    kwargs: dict = {"name": req.name, "project": project_key, "released": req.released}
    if req.description:  kwargs["description"] = req.description
    if req.release_date: kwargs["releaseDate"]  = req.release_date
    v = get_jira().create_version(**kwargs)
    return {"id": v.id, "name": v.name}


# ── Board & Sprint ─────────────────────────────────────────────────────────────

@app.get("/jira/boards", tags=["Jira - Board & Sprint"])
def jira_get_boards(project_key: Optional[str] = None, _: str = Depends(verify_api_key)):
    kwargs: dict = {}
    if project_key: kwargs["projectKeyOrID"] = project_key
    try:
        boards = get_jira().boards(**kwargs)
        return [{"id": b.id, "name": b.name, "type": b.type} for b in boards]
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/jira/board/{board_id}/sprints", tags=["Jira - Board & Sprint"])
def jira_get_sprints(board_id: int, state: str = "active,future",
                     _: str = Depends(verify_api_key)):
    sprints = get_jira().sprints(board_id, state=state)
    return [{"id": s.id, "name": s.name, "state": s.state} for s in sprints]


@app.get("/jira/board/{board_id}/issues", tags=["Jira - Board & Sprint"])
def jira_get_board_issues(board_id: int, max_results: int = 20,
                           _: str = Depends(verify_api_key)):
    try:
        issues = get_jira().get_issues_for_board(board_id, maxResults=max_results)
        return [{"key": i.key, "summary": i.fields.summary, "status": i.fields.status.name}
                for i in issues]
    except Exception as e:
        raise HTTPException(400, str(e))


class SprintIssueReq(BaseModel):
    sprint_id: int
    issue_key: str

@app.post("/jira/sprint/add-issue", response_model=Msg, tags=["Jira - Board & Sprint"])
def jira_add_to_sprint(req: SprintIssueReq, _: str = Depends(verify_api_key)):
    get_jira().add_issues_to_sprint(req.sprint_id, [req.issue_key])
    return Msg(message=f"{req.issue_key} → Sprint {req.sprint_id}'e eklendi.")


# ══════════════════════════════════════════════════════════════════════════════
# CONFLUENCE — SORGULAMA
# ══════════════════════════════════════════════════════════════════════════════

class CFSearchReq(BaseModel):
    query: str
    space_key: Optional[str] = None
    content_type: str = "page"
    limit: int = 10

@app.post("/confluence/search", tags=["Confluence - Sorgulama"])
def cf_search(req: CFSearchReq, _: str = Depends(verify_api_key)):
    """Confluence'da CQL ile ara."""
    cf  = get_confluence()
    cql = f'text ~ "{req.query}" AND type = {req.content_type}'
    if req.space_key: cql += f' AND space = "{req.space_key}"'
    results = cf.cql(cql, limit=req.limit).get("results", [])
    return [{"id": r.get("content", {}).get("id", ""),
             "title": r.get("title", "—"),
             "space": r.get("resultGlobalContainer", {}).get("title", "—"),
             "url": cf.url + r.get("url", "")} for r in results]


@app.get("/confluence/spaces", tags=["Confluence - Sorgulama"])
def cf_list_spaces(_: str = Depends(verify_api_key)):
    spaces = get_confluence().get_all_spaces(start=0, limit=50).get("results", [])
    return [{"key": s["key"], "name": s["name"], "type": s.get("type", "—")} for s in spaces]


@app.get("/confluence/space/{space_key}/pages", tags=["Confluence - Sorgulama"])
def cf_list_pages(space_key: str, limit: int = 25, _: str = Depends(verify_api_key)):
    pages = get_confluence().get_all_pages_from_space(space_key, start=0, limit=limit)
    return [{"id": p["id"], "title": p["title"]} for p in pages]


@app.get("/confluence/page/{page_id}/children", tags=["Confluence - Sorgulama"])
def cf_get_children(page_id: str, _: str = Depends(verify_api_key)):
    children = get_confluence().get_page_child_by_type(page_id, type="page")
    return [{"id": c["id"], "title": c["title"]} for c in children]


# ══════════════════════════════════════════════════════════════════════════════
# CONFLUENCE — SAYFA CRUD
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/confluence/page/{page_id}", tags=["Confluence - Sayfa"])
def cf_get_page(page_id: str, _: str = Depends(verify_api_key)):
    import re
    cf   = get_confluence()
    page = cf.get_page_by_id(page_id, expand="body.storage")
    if not page: raise HTTPException(404, "Sayfa bulunamadı.")
    raw   = page.get("body", {}).get("storage", {}).get("value", "")
    clean = re.sub(r"<[^>]+>", "", raw).strip()
    return {"id": page_id, "title": page.get("title"),
            "content": clean[:5000], "url": cf.url + page.get("_links", {}).get("webui", "")}


class CFCreateReq(BaseModel):
    space_key: str
    title: str
    content: str = ""
    parent_id: Optional[str] = None

@app.post("/confluence/page", response_model=Msg, tags=["Confluence - Sayfa"])
def cf_create_page(req: CFCreateReq, _: str = Depends(verify_api_key)):
    cf   = get_confluence()
    body = req.content if req.content.strip().startswith("<") else f"<p>{req.content}</p>"
    kwargs: dict = {"space": req.space_key, "title": req.title, "body": body}
    if req.parent_id: kwargs["parent_id"] = req.parent_id
    page = cf.create_page(**kwargs)
    url  = cf.url + page.get("_links", {}).get("webui", "")
    return Msg(message=f"Sayfa oluşturuldu: {req.title} (ID:{page.get('id')}) — {url}")


class CFUpdateReq(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None

@app.put("/confluence/page/{page_id}", response_model=Msg, tags=["Confluence - Sayfa"])
def cf_update_page(page_id: str, req: CFUpdateReq, _: str = Depends(verify_api_key)):
    cf   = get_confluence()
    page = cf.get_page_by_id(page_id, expand="body.storage")
    if not page: raise HTTPException(404, "Sayfa bulunamadı.")
    new_title   = req.title   or page["title"]
    new_content = page["body"]["storage"]["value"]
    if req.content:
        new_content = req.content if req.content.strip().startswith("<") else f"<p>{req.content}</p>"
    cf.update_page(page_id=page_id, title=new_title, body=new_content)
    return Msg(message=f"Sayfa güncellendi: {new_title}")


@app.delete("/confluence/page/{page_id}", response_model=Msg, tags=["Confluence - Sayfa"])
def cf_delete_page(page_id: str, _: str = Depends(verify_api_key)):
    get_confluence().remove_page(page_id)
    return Msg(message=f"Sayfa {page_id} silindi.")


# ══════════════════════════════════════════════════════════════════════════════
# CONFLUENCE — YORUM & ETİKET & ATTACHMENT
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/confluence/page/{page_id}/comments", tags=["Confluence - Yorum & Etiket"])
def cf_get_comments(page_id: str, _: str = Depends(verify_api_key)):
    import re
    comments = get_confluence().get_page_comments(page_id).get("results", [])
    return [{"author": c.get("history", {}).get("createdBy", {}).get("displayName", "—"),
             "created": c.get("history", {}).get("createdDate", "—")[:10],
             "body": re.sub(r"<[^>]+>", "", c.get("body", {}).get("storage", {}).get("value", ""))[:200]}
            for c in comments]


class CFCommentReq(BaseModel):
    comment: str

@app.post("/confluence/page/{page_id}/comment", response_model=Msg, tags=["Confluence - Yorum & Etiket"])
def cf_add_comment(page_id: str, req: CFCommentReq, _: str = Depends(verify_api_key)):
    get_confluence().add_comment(page_id, req.comment)
    return Msg(message=f"Sayfa {page_id}'e yorum eklendi.")


@app.get("/confluence/page/{page_id}/labels", tags=["Confluence - Yorum & Etiket"])
def cf_get_labels(page_id: str, _: str = Depends(verify_api_key)):
    labels = get_confluence().get_page_labels(page_id).get("results", [])
    return [l["name"] for l in labels]


class CFLabelReq(BaseModel):
    label: str

@app.post("/confluence/page/{page_id}/label", response_model=Msg, tags=["Confluence - Yorum & Etiket"])
def cf_add_label(page_id: str, req: CFLabelReq, _: str = Depends(verify_api_key)):
    get_confluence().set_page_label(page_id, req.label)
    return Msg(message=f"'{req.label}' etiketi eklendi.")


@app.get("/confluence/page/{page_id}/attachments", tags=["Confluence - Attachment"])
def cf_get_attachments(page_id: str, _: str = Depends(verify_api_key)):
    attachments = get_confluence().get_attachments_from_content(page_id).get("results", [])
    return [{"title": a["title"],
             "type": a.get("metadata", {}).get("mediaType", "—"),
             "created": a.get("history", {}).get("createdDate", "—")[:10]}
            for a in attachments]


# ══════════════════════════════════════════════════════════════════════════════
# CONFLUENCE — JİRA BAĞLANTISI
# ══════════════════════════════════════════════════════════════════════════════

class CFLinkJiraReq(BaseModel):
    jira_issue_key: str

@app.post("/confluence/page/{page_id}/link-jira", response_model=Msg, tags=["Confluence - Jira Bağlantısı"])
def cf_link_jira(page_id: str, req: CFLinkJiraReq, _: str = Depends(verify_api_key)):
    cf   = get_confluence()
    page = cf.get_page_by_id(page_id, expand="body.storage")
    if not page: raise HTTPException(404, "Sayfa bulunamadı.")
    macro = (f'<p><ac:structured-macro ac:name="jira">'
             f'<ac:parameter ac:name="key">{req.jira_issue_key}</ac:parameter>'
             f'</ac:structured-macro></p>')
    cf.update_page(page_id=page_id, title=page["title"],
                   body=page["body"]["storage"]["value"] + macro)
    return Msg(message=f"Sayfa {page_id} ↔ {req.jira_issue_key} ilişkilendirildi.")


# ══════════════════════════════════════════════════════════════════════════════
# AGENT
# ══════════════════════════════════════════════════════════════════════════════

class ChatReq(BaseModel):
    message: str

@app.post("/chat", tags=["Agent"])
def chat(req: ChatReq, _: str = Depends(verify_api_key)):
    """Serbest metin — tüm Jira ve Confluence tool'larını kullanır."""
    jira       = get_jira()
    llm        = get_llm()
    confluence = get_confluence() if CONFLUENCE_EMAIL else None
    result     = run_agent(req.message, jira, llm, confluence)
    return {"output": result.output,
            "logs": [{"ts": l.ts, "msg": l.msg, "level": l.level} for l in result.logs],
            "success": result.success}
