"""
jira_tools.py
─────────────
Tüm Jira CrewAI tool'ları.
mcp-atlassian'daki Jira fonksiyonlarının tamamını kapsar.
"""

import os
from typing import Optional
from datetime import datetime

from pydantic import BaseModel
from jira import JIRA


class _JiraTool:
    name: str = ""
    description: str = ""
    args_schema = None

    def __init__(self, jira: JIRA):
        self.jira = jira


# ══════════════════════════════════════════════════════════════════════════════
# SORGULAMA
# ══════════════════════════════════════════════════════════════════════════════

class QueryIssuesTool(_JiraTool):
    name: str = "jira_search_issues"
    description: str = (
        "JQL ile Jira issue sorgular. "
        "Örn: 'project=PROJ AND status=Open AND assignee=currentUser()'"
    )
    class _In(BaseModel):
        jql: str
        max_results: int = 10
    args_schema: type[BaseModel] = _In

    def _run(self, jql: str, max_results: int = 10) -> str:
        issues = self.jira.search_issues(jql, maxResults=max_results)
        if not issues:
            return "Sonuç bulunamadı."
        return "\n".join(
            f"{i.key} | {i.fields.summary[:55]} | {i.fields.status.name} | "
            f"{getattr(i.fields.assignee, 'displayName', '—')} | "
            f"{getattr(i.fields.priority, 'name', '—')}"
            for i in issues
        )


class GetIssueTool(_JiraTool):
    name: str = "jira_get_issue"
    description: str = "Belirli bir Jira issue'sunun tüm detaylarını getirir."
    class _In(BaseModel):
        issue_key: str
    args_schema: type[BaseModel] = _In

    def _run(self, issue_key: str) -> str:
        i = self.jira.issue(issue_key)
        labels    = ", ".join(i.fields.labels) if i.fields.labels else "—"
        components = ", ".join(c.name for c in i.fields.components) if i.fields.components else "—"
        subtasks  = ", ".join(s.key for s in i.fields.subtasks) if i.fields.subtasks else "—"
        return (
            f"Key: {i.key}\n"
            f"Özet: {i.fields.summary}\n"
            f"Tür: {i.fields.issuetype.name}\n"
            f"Durum: {i.fields.status.name}\n"
            f"Öncelik: {getattr(i.fields.priority, 'name', '—')}\n"
            f"Atanan: {getattr(i.fields.assignee, 'displayName', '—')}\n"
            f"Reporter: {getattr(i.fields.reporter, 'displayName', '—')}\n"
            f"Proje: {i.fields.project.key}\n"
            f"Etiketler: {labels}\n"
            f"Bileşenler: {components}\n"
            f"Alt görevler: {subtasks}\n"
            f"Oluşturulma: {str(i.fields.created)[:10]}\n"
            f"Güncelleme: {str(i.fields.updated)[:10]}\n"
            f"Açıklama: {str(i.fields.description or '')[:300]}\n"
            f"URL: {i.permalink()}"
        )


class GetAllProjectsTool(_JiraTool):
    name: str = "jira_get_all_projects"
    description: str = "Tüm Jira projelerini listeler."
    class _In(BaseModel):
        include_archived: bool = False
    args_schema: type[BaseModel] = _In

    def _run(self, include_archived: bool = False) -> str:
        projects = self.jira.projects()
        rows = []
        for p in projects:
            if not include_archived and getattr(p, "archived", False):
                continue
            rows.append(f"{p.key} | {p.name} | {getattr(p, 'projectTypeKey', '—')}")
        return "\n".join(rows) or "Proje bulunamadı."


class GetProjectIssuesTool(_JiraTool):
    name: str = "jira_get_project_issues"
    description: str = "Bir projedeki tüm issue'ları listeler. status ile filtrelenebilir."
    class _In(BaseModel):
        project_key: str
        status: Optional[str] = None
        max_results: int = 20
    args_schema: type[BaseModel] = _In

    def _run(self, project_key: str, status=None, max_results: int = 20) -> str:
        jql = f"project={project_key}"
        if status:
            jql += f" AND status='{status}'"
        jql += " ORDER BY created DESC"
        issues = self.jira.search_issues(jql, maxResults=max_results)
        if not issues:
            return "Issue bulunamadı."
        return "\n".join(
            f"{i.key} | {i.fields.summary[:55]} | {i.fields.status.name} | "
            f"{getattr(i.fields.assignee, 'displayName', '—')}"
            for i in issues
        )


class GetTransitionsTool(_JiraTool):
    name: str = "jira_get_transitions"
    description: str = "Bir issue için mevcut durum geçişlerini listeler."
    class _In(BaseModel):
        issue_key: str
    args_schema: type[BaseModel] = _In

    def _run(self, issue_key: str) -> str:
        transitions = self.jira.transitions(issue_key)
        return "\n".join(f"ID:{t['id']} | {t['name']}" for t in transitions)


class SearchFieldsTool(_JiraTool):
    name: str = "jira_search_fields"
    description: str = "Jira'daki mevcut alanları (fields) listeler veya arar."
    class _In(BaseModel):
        query: Optional[str] = None
    args_schema: type[BaseModel] = _In

    def _run(self, query=None) -> str:
        fields = self.jira.fields()
        if query:
            fields = [f for f in fields if query.lower() in f["name"].lower()]
        return "\n".join(f"{f['id']} | {f['name']} | {f['schema'].get('type','—')}"
                         for f in fields[:50])


class GetUserProfileTool(_JiraTool):
    name: str = "jira_get_user_profile"
    description: str = "Kullanıcı profil bilgilerini getirir. email veya username ile aranır."
    class _In(BaseModel):
        email: Optional[str] = None
        username: Optional[str] = None
    args_schema: type[BaseModel] = _In

    def _run(self, email=None, username=None) -> str:
        try:
            if email:
                users = self.jira.search_users(email)
            elif username:
                users = self.jira.search_users(username)
            else:
                return "email veya username zorunlu."
            if not users:
                return "Kullanıcı bulunamadı."
            u = users[0]
            return (
                f"Ad: {u.displayName}\n"
                f"Email: {getattr(u, 'emailAddress', '—')}\n"
                f"Username: {u.name}\n"
                f"Aktif: {u.active}"
            )
        except Exception as e:
            return f"Hata: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# OLUŞTURMA / GÜNCELLEME / SİLME
# ══════════════════════════════════════════════════════════════════════════════

class CreateIssueTool(_JiraTool):
    name: str = "jira_create_issue"
    description: str = "Jira'da yeni issue oluşturur. Tür: Bug, Story, Task, Epic, Sub-task"
    class _In(BaseModel):
        project_key: str
        summary: str
        description: str = ""
        issue_type: str = "Story"
        assignee_email: Optional[str] = None
        priority: Optional[str] = None
        labels: Optional[list[str]] = None
        components: Optional[list[str]] = None
        parent_key: Optional[str] = None
    args_schema: type[BaseModel] = _In

    def _run(self, project_key, summary, description="", issue_type="Story",
             assignee_email=None, priority=None, labels=None,
             components=None, parent_key=None) -> str:
        fields: dict = {
            "project":     {"key": project_key},
            "summary":     summary,
            "description": description,
            "issuetype":   {"name": issue_type},
        }
        if assignee_email: fields["assignee"]   = {"name": assignee_email}  # Jira Server: name=username veya email
        if priority:       fields["priority"]   = {"name": priority}
        if labels:         fields["labels"]     = labels
        if components:     fields["components"] = [{"name": c} for c in components]
        if parent_key:     fields["parent"]     = {"key": parent_key}
        issue = self.jira.create_issue(fields=fields)
        return f"Issue oluşturuldu: {issue.key} — {issue.permalink()}"


class BatchCreateIssuesTool(_JiraTool):
    name: str = "jira_batch_create_issues"
    description: str = (
        "Birden fazla Jira issue'sunu tek seferde oluşturur. "
        "issues: [{project_key, summary, issue_type, description, priority}]"
    )
    class _In(BaseModel):
        issues: list[dict]
    args_schema: type[BaseModel] = _In

    def _run(self, issues: list[dict]) -> str:
        results = []
        for i, item in enumerate(issues):
            try:
                fields: dict = {
                    "project":     {"key": item["project_key"]},
                    "summary":     item["summary"],
                    "description": item.get("description", ""),
                    "issuetype":   {"name": item.get("issue_type", "Story")},
                }
                if item.get("assignee_email"): fields["assignee"] = {"name": item["assignee_email"]}
                if item.get("priority"):       fields["priority"]  = {"name": item["priority"]}
                if item.get("labels"):         fields["labels"]    = item["labels"]
                issue = self.jira.create_issue(fields=fields)
                results.append(f"✓ {issue.key}: {item['summary'][:50]}")
            except Exception as e:
                results.append(f"✗ [{i+1}] {item.get('summary','?')[:50]} — {e}")
        return f"{len(issues)} issue işlendi:\n" + "\n".join(results)


class UpdateIssueTool(_JiraTool):
    name: str = "jira_update_issue"
    description: str = "Jira issue günceller: başlık, açıklama, atanan, öncelik, durum, proje"
    class _In(BaseModel):
        issue_key: str
        summary: Optional[str] = None
        description: Optional[str] = None
        status: Optional[str] = None
        assignee_email: Optional[str] = None
        priority: Optional[str] = None
        project_key: Optional[str] = None
        labels: Optional[list[str]] = None
    args_schema: type[BaseModel] = _In

    def _run(self, issue_key, summary=None, description=None, status=None,
             assignee_email=None, priority=None, project_key=None, labels=None) -> str:
        issue = self.jira.issue(issue_key)
        upd: dict = {}
        if summary:        upd["summary"]     = summary
        if description:    upd["description"] = description
        if assignee_email: upd["assignee"]    = {"emailAddress": assignee_email}
        if priority:       upd["priority"]    = {"name": priority}
        if project_key:    upd["project"]     = {"key": project_key}
        if labels is not None: upd["labels"]  = labels
        if upd: issue.update(fields=upd)
        if status:
            transitions = self.jira.transitions(issue)
            match = next((t for t in transitions if t["name"].lower() == status.lower()), None)
            if match:
                self.jira.transition_issue(issue, match["id"])
            else:
                available = [t["name"] for t in transitions]
                return f"{issue_key} güncellendi ama '{status}' geçişi bulunamadı. Mevcut: {available}"
        return f"{issue_key} güncellendi."


class TransitionIssueTool(_JiraTool):
    name: str = "jira_transition_issue"
    description: str = "Issue'nun durumunu değiştirir. Mevcut geçişleri jira_get_transitions ile öğren."
    class _In(BaseModel):
        issue_key: str
        transition_name: str
    args_schema: type[BaseModel] = _In

    def _run(self, issue_key: str, transition_name: str) -> str:
        transitions = self.jira.transitions(issue_key)
        match = next((t for t in transitions if t["name"].lower() == transition_name.lower()), None)
        if not match:
            available = [t["name"] for t in transitions]
            return f"'{transition_name}' geçişi bulunamadı. Mevcut: {available}"
        self.jira.transition_issue(issue_key, match["id"])
        return f"{issue_key} → '{transition_name}' yapıldı."


class DeleteIssueTool(_JiraTool):
    name: str = "jira_delete_issue"
    description: str = "Jira issue'sunu siler. confirm=true ile onaylanmalı. GERİ ALINAMAZ!"
    class _In(BaseModel):
        issue_key: str
        confirm: bool = False
    args_schema: type[BaseModel] = _In

    def _run(self, issue_key: str, confirm: bool = False) -> str:
        if not confirm:
            return f"⚠️ {issue_key} silinecek. Onaylamak için confirm=true ile tekrar çağır."
        self.jira.issue(issue_key).delete()
        return f"{issue_key} silindi."


# ══════════════════════════════════════════════════════════════════════════════
# YORUM & WORKLOG
# ══════════════════════════════════════════════════════════════════════════════

class AddCommentTool(_JiraTool):
    name: str = "jira_add_comment"
    description: str = "Jira issue'suna yorum ekler."
    class _In(BaseModel):
        issue_key: str
        comment: str
    args_schema: type[BaseModel] = _In

    def _run(self, issue_key: str, comment: str) -> str:
        self.jira.add_comment(issue_key, comment)
        return f"{issue_key} issue'suna yorum eklendi."


class WorklogTool(_JiraTool):
    name: str = "jira_manage_worklog"
    description: str = (
        "Worklog ekler (add) veya listeler (list). "
        "time_spent formatı: '2h 30m', '1d', '4h'"
    )
    class _In(BaseModel):
        action: str
        issue_key: str
        time_spent: Optional[str] = None
        comment: Optional[str] = None
        started: Optional[str] = None
    args_schema: type[BaseModel] = _In

    def _run(self, action: str, issue_key: str,
             time_spent=None, comment=None, started=None) -> str:
        if action == "add":
            if not time_spent:
                return "time_spent zorunlu. Örn: '2h 30m'"
            kwargs: dict = {}
            if comment: kwargs["comment"] = comment
            if started: kwargs["started"] = datetime.strptime(started, "%Y-%m-%d %H:%M")
            self.jira.add_worklog(issue_key, timeSpent=time_spent, **kwargs)
            return f"{issue_key} — {time_spent} worklog eklendi."
        if action == "list":
            worklogs = self.jira.worklogs(issue_key)
            if not worklogs:
                return "Worklog bulunamadı."
            return "\n".join(
                f"{w.author.displayName} | {w.timeSpent} | "
                f"{w.started[:10]} | {getattr(w, 'comment', '—')[:40]}"
                for w in worklogs
            )
        return f"Bilinmeyen aksiyon: {action}"


# ══════════════════════════════════════════════════════════════════════════════
# ATTACHMENT
# ══════════════════════════════════════════════════════════════════════════════

class AttachmentTool(_JiraTool):
    name: str = "jira_manage_attachment"
    description: str = (
        "Ekleri listeler (list) veya dosya ekler (upload). "
        "upload için file_path zorunlu."
    )
    class _In(BaseModel):
        action: str
        issue_key: str
        file_path: Optional[str] = None
    args_schema: type[BaseModel] = _In

    def _run(self, action: str, issue_key: str, file_path=None) -> str:
        issue = self.jira.issue(issue_key)
        if action == "list":
            attachments = issue.fields.attachment
            if not attachments:
                return f"{issue_key} issue'sunda ek bulunamadı."
            return "\n".join(
                f"{a.filename} | {a.size} bytes | {a.created[:10]} | {a.author.displayName}"
                for a in attachments
            )
        if action == "upload":
            if not file_path:
                return "file_path zorunlu."
            if not os.path.exists(file_path):
                return f"Dosya bulunamadı: {file_path}"
            with open(file_path, "rb") as f:
                self.jira.add_attachment(issue=issue, attachment=f)
            return f"{os.path.basename(file_path)} → {issue_key}'e eklendi."
        return f"Bilinmeyen aksiyon: {action}"


# ══════════════════════════════════════════════════════════════════════════════
# ISSUE LİNKLEME & EPİC
# ══════════════════════════════════════════════════════════════════════════════

class IssueLinkTool(_JiraTool):
    name: str = "jira_manage_issue_link"
    description: str = (
        "Issue'lar arasında link oluşturur (create) veya kaldırır (delete) veya link tiplerini listeler (list_types). "
        "Örn: 'blocks', 'is blocked by', 'relates to', 'duplicates'"
    )
    class _In(BaseModel):
        action: str
        link_type: Optional[str] = None
        inward_issue: Optional[str] = None
        outward_issue: Optional[str] = None
        link_id: Optional[str] = None
    args_schema: type[BaseModel] = _In

    def _run(self, action: str, link_type=None, inward_issue=None,
             outward_issue=None, link_id=None) -> str:
        if action == "list_types":
            types = self.jira.issue_link_types()
            return "\n".join(
                f"{lt.name} | inward: {lt.inward} | outward: {lt.outward}"
                for lt in types
            )
        if action == "create":
            if not (link_type and inward_issue and outward_issue):
                return "link_type, inward_issue ve outward_issue zorunlu."
            self.jira.create_issue_link(
                type=link_type,
                inwardIssue=inward_issue,
                outwardIssue=outward_issue,
            )
            return f"{inward_issue} ↔ {outward_issue} ({link_type}) bağlantısı oluşturuldu."
        if action == "delete":
            if not link_id:
                return "link_id zorunlu."
            self.jira.delete_issue_link(link_id)
            return f"Link {link_id} silindi."
        return f"Bilinmeyen aksiyon: {action}"


class EpicTool(_JiraTool):
    name: str = "jira_link_to_epic"
    description: str = "Issue'yu bir Epic'e bağlar."
    class _In(BaseModel):
        issue_key: str
        epic_key: str
    args_schema: type[BaseModel] = _In

    def _run(self, issue_key: str, epic_key: str) -> str:
        issue = self.jira.issue(issue_key)
        # Epic link field ID — server'da genellikle customfield_10014
        for field_id in ["customfield_10014", "customfield_10008"]:
            try:
                issue.update(fields={field_id: epic_key})
                return f"{issue_key} → Epic {epic_key}'e bağlandı."
            except Exception:
                continue
        return f"Epic link alanı bulunamadı. Jira yöneticinizle iletişime geçin."


# ══════════════════════════════════════════════════════════════════════════════
# VERSİYON / RELEASE
# ══════════════════════════════════════════════════════════════════════════════

class VersionTool(_JiraTool):
    name: str = "jira_manage_version"
    description: str = (
        "Proje versiyonlarını listeler (list), oluşturur (create) veya günceller (update). "
        "Release/Fix version yönetimi için kullanılır."
    )
    class _In(BaseModel):
        action: str
        project_key: str
        name: Optional[str] = None
        description: Optional[str] = None
        release_date: Optional[str] = None
        released: Optional[bool] = None
        version_id: Optional[str] = None
    args_schema: type[BaseModel] = _In

    def _run(self, action: str, project_key: str, name=None, description=None,
             release_date=None, released=None, version_id=None) -> str:
        if action == "list":
            versions = self.jira.project_versions(project_key)
            if not versions:
                return "Versiyon bulunamadı."
            return "\n".join(
                f"ID:{v.id} | {v.name} | Released:{getattr(v,'released',False)} | "
                f"{getattr(v,'releaseDate','—')}"
                for v in versions
            )
        if action == "create":
            if not name:
                return "name zorunlu."
            kwargs: dict = {"name": name, "project": project_key}
            if description:  kwargs["description"]  = description
            if release_date: kwargs["releaseDate"]  = release_date
            if released is not None: kwargs["released"] = released
            v = self.jira.create_version(**kwargs)
            return f"Versiyon oluşturuldu: {v.name} (ID:{v.id})"
        if action == "update":
            if not version_id:
                return "version_id zorunlu."
            v = self.jira.version(version_id)
            kwargs = {}
            if name:        kwargs["name"]        = name
            if description: kwargs["description"] = description
            if release_date: kwargs["releaseDate"] = release_date
            if released is not None: kwargs["released"] = released
            v.update(**kwargs)
            return f"Versiyon {version_id} güncellendi."
        return f"Bilinmeyen aksiyon: {action}"


# ══════════════════════════════════════════════════════════════════════════════
# BOARD & SPRINT
# ══════════════════════════════════════════════════════════════════════════════

class BoardTool(_JiraTool):
    name: str = "jira_get_agile_boards"
    description: str = "Jira Agile board'larını listeler. project_key ile filtrelenebilir."
    class _In(BaseModel):
        project_key: Optional[str] = None
        board_type: Optional[str] = None
    args_schema: type[BaseModel] = _In

    def _run(self, project_key=None, board_type=None) -> str:
        try:
            kwargs: dict = {}
            if project_key: kwargs["projectKeyOrID"] = project_key
            if board_type:  kwargs["type"] = board_type
            boards = self.jira.boards(**kwargs)
            if not boards:
                return "Board bulunamadı."
            return "\n".join(
                f"ID:{b.id} | {b.name} | {b.type}"
                for b in boards
            )
        except Exception as e:
            return f"Hata: {e}"


class BoardIssuesTool(_JiraTool):
    name: str = "jira_get_board_issues"
    description: str = "Bir board'daki issue'ları listeler."
    class _In(BaseModel):
        board_id: int
        max_results: int = 20
        jql: Optional[str] = None
    args_schema: type[BaseModel] = _In

    def _run(self, board_id: int, max_results: int = 20, jql=None) -> str:
        try:
            issues = self.jira.get_issues_for_board(board_id, jql=jql, maxResults=max_results)
            if not issues:
                return "Issue bulunamadı."
            return "\n".join(
                f"{i.key} | {i.fields.summary[:55]} | {i.fields.status.name}"
                for i in issues
            )
        except Exception as e:
            return f"Hata: {e}"


class SprintTool(_JiraTool):
    name: str = "jira_manage_sprint"
    description: str = (
        "Sprint işlemleri: listeler (list), oluşturur (create), günceller (update), "
        "issue ekler (add_issue). "
        "state: active, future, closed"
    )
    class _In(BaseModel):
        action: str
        board_id: Optional[int] = None
        sprint_id: Optional[int] = None
        issue_key: Optional[str] = None
        name: Optional[str] = None
        goal: Optional[str] = None
        start_date: Optional[str] = None
        end_date: Optional[str] = None
        state: Optional[str] = None
    args_schema: type[BaseModel] = _In

    def _run(self, action: str, board_id=None, sprint_id=None, issue_key=None,
             name=None, goal=None, start_date=None, end_date=None, state=None) -> str:
        if action == "list":
            if not board_id:
                return "board_id zorunlu."
            sprints = self.jira.sprints(board_id, state=state or "active,future")
            return "\n".join(
                f"ID:{s.id} | {s.name} | {s.state}"
                for s in sprints
            ) or "Sprint bulunamadı."
        if action == "list_issues":
            if not sprint_id:
                return "sprint_id zorunlu."
            issues = self.jira.get_issues_for_sprint_in_board(board_id, sprint_id)
            return "\n".join(
                f"{i.key} | {i.fields.summary[:55]} | {i.fields.status.name}"
                for i in issues
            ) or "Issue bulunamadı."
        if action == "create":
            if not (board_id and name):
                return "board_id ve name zorunlu."
            sprint = self.jira.create_sprint(name=name, board_id=board_id,
                                             startDate=start_date, endDate=end_date, goal=goal)
            return f"Sprint oluşturuldu: {sprint.name} (ID:{sprint.id})"
        if action == "update":
            if not sprint_id:
                return "sprint_id zorunlu."
            kwargs: dict = {}
            if name:       kwargs["name"]      = name
            if goal:       kwargs["goal"]      = goal
            if start_date: kwargs["startDate"] = start_date
            if end_date:   kwargs["endDate"]   = end_date
            if state:      kwargs["state"]     = state
            self.jira.update_sprint(sprint_id, **kwargs)
            return f"Sprint {sprint_id} güncellendi."
        if action == "add_issue":
            if not (sprint_id and issue_key):
                return "sprint_id ve issue_key zorunlu."
            self.jira.add_issues_to_sprint(sprint_id, [issue_key])
            return f"{issue_key} → Sprint {sprint_id}'e eklendi."
        return f"Bilinmeyen aksiyon: {action}"


# ══════════════════════════════════════════════════════════════════════════════
# CHANGELOG
# ══════════════════════════════════════════════════════════════════════════════

class ChangelogTool(_JiraTool):
    name: str = "jira_get_changelog"
    description: str = "Issue'nun değişiklik geçmişini (changelog) getirir."
    class _In(BaseModel):
        issue_key: str
        max_results: int = 20
    args_schema: type[BaseModel] = _In

    def _run(self, issue_key: str, max_results: int = 20) -> str:
        issue = self.jira.issue(issue_key, expand="changelog")
        histories = issue.changelog.histories[:max_results]
        if not histories:
            return "Değişiklik geçmişi bulunamadı."
        rows = []
        for h in histories:
            for item in h.items:
                rows.append(
                    f"{str(h.created)[:16]} | {h.author.displayName} | "
                    f"{item.field}: '{item.fromString}' → '{item.toString}'"
                )
        return "\n".join(rows)


class SprintIssuesByNameTool(_JiraTool):
    name: str = "jira_get_sprint_issues_by_name"
    description: str = (
        "Sprint adını vererek o sprintteki tüm issue'ları listeler. "
        "Board ID veya Sprint ID gerekmez. "
        "Örn: sprint_name='Sprint 5' veya sprint_name='abc'"
    )
    class _In(BaseModel):
        sprint_name: str
        project_key: Optional[str] = None
        max_results: int = 30
    args_schema: type[BaseModel] = _In

    def _run(self, sprint_name: str, project_key=None, max_results: int = 30) -> str:
        jql = f'sprint = "{sprint_name}"'
        if project_key:
            jql += f" AND project = {project_key}"
        jql += " ORDER BY status ASC"
        issues = self.jira.search_issues(jql, maxResults=max_results)
        if not issues:
            return f"'{sprint_name}' sprint'inde issue bulunamadı."
        return "\n".join(
            f"{i.key} | {i.fields.summary[:55]} | {i.fields.status.name} | "
            f"{getattr(i.fields.assignee, 'displayName', '—')} | "
            f"{getattr(i.fields.priority, 'name', '—')}"
            for i in issues
        )


# ══════════════════════════════════════════════════════════════════════════════
# FACTORY
# ══════════════════════════════════════════════════════════════════════════════

def get_all_jira_tools(jira: JIRA) -> list:
    """Tüm Jira tool'larını döndürür."""
    return [
        QueryIssuesTool(jira=jira),
        GetIssueTool(jira=jira),
        GetAllProjectsTool(jira=jira),
        GetProjectIssuesTool(jira=jira),
        GetTransitionsTool(jira=jira),
        SearchFieldsTool(jira=jira),
        GetUserProfileTool(jira=jira),
        CreateIssueTool(jira=jira),
        BatchCreateIssuesTool(jira=jira),
        UpdateIssueTool(jira=jira),
        TransitionIssueTool(jira=jira),
        DeleteIssueTool(jira=jira),
        AddCommentTool(jira=jira),
        WorklogTool(jira=jira),
        AttachmentTool(jira=jira),
        IssueLinkTool(jira=jira),
        EpicTool(jira=jira),
        VersionTool(jira=jira),
        BoardTool(jira=jira),
        BoardIssuesTool(jira=jira),
        SprintTool(jira=jira),
        ChangelogTool(jira=jira),
        SprintIssuesByNameTool(jira=jira),
    ]
