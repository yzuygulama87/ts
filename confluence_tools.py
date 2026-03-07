"""
confluence_tools.py
───────────────────
Tüm Confluence CrewAI tool'ları.
mcp-atlassian'daki Confluence fonksiyonlarının tamamını kapsar.
"""

import re
import os
from typing import Optional

from crewai.tools import BaseTool
from atlassian import Confluence
from pydantic import BaseModel, Field


class _ConfluenceTool(BaseTool):
    confluence: Confluence = Field(exclude=True)
    class Config:
        arbitrary_types_allowed = True


def _strip_html(html: str) -> str:
    """HTML tag'lerini temizler."""
    return re.sub(r"<[^>]+>", "", html).strip()


def _to_html(content: str) -> str:
    """Düz metni HTML'e çevirir."""
    return content if content.strip().startswith("<") else f"<p>{content}</p>"


# ══════════════════════════════════════════════════════════════════════════════
# ARAMA & LİSTELEME
# ══════════════════════════════════════════════════════════════════════════════

class SearchPagesTool(_ConfluenceTool):
    name: str = "confluence_search"
    description: str = (
        "Confluence'da CQL ile sayfa ve içerik arar. "
        "Örn: query='onboarding', space_key='DEV'"
    )
    class _In(BaseModel):
        query: str
        space_key: Optional[str] = None
        content_type: str = "page"
        limit: int = 10
    args_schema: type[BaseModel] = _In

    def _run(self, query: str, space_key=None,
             content_type: str = "page", limit: int = 10) -> str:
        cql = f'text ~ "{query}" AND type = {content_type}'
        if space_key:
            cql += f' AND space = "{space_key}"'
        results = self.confluence.cql(cql, limit=limit).get("results", [])
        if not results:
            return "Sonuç bulunamadı."
        rows = []
        for r in results:
            title = r.get("title", "—")
            space = r.get("resultGlobalContainer", {}).get("title", "—")
            cid   = r.get("content", {}).get("id", "—")
            url   = self.confluence.url + r.get("url", "")
            rows.append(f"ID:{cid} | {title} | Space:{space} | {url}")
        return "\n".join(rows)


class ListSpacesTool(_ConfluenceTool):
    name: str = "confluence_list_spaces"
    description: str = "Tüm Confluence space'lerini listeler."
    class _In(BaseModel):
        limit: int = 50
    args_schema: type[BaseModel] = _In

    def _run(self, limit: int = 50) -> str:
        spaces = self.confluence.get_all_spaces(start=0, limit=limit).get("results", [])
        if not spaces:
            return "Space bulunamadı."
        return "\n".join(
            f"{s['key']} | {s['name']} | {s.get('type','—')}"
            for s in spaces
        )


class ListPagesTool(_ConfluenceTool):
    name: str = "confluence_list_pages"
    description: str = "Bir space'deki sayfaları listeler."
    class _In(BaseModel):
        space_key: str
        limit: int = 25
    args_schema: type[BaseModel] = _In

    def _run(self, space_key: str, limit: int = 25) -> str:
        pages = self.confluence.get_all_pages_from_space(space_key, start=0, limit=limit)
        if not pages:
            return "Sayfa bulunamadı."
        return "\n".join(f"ID:{p['id']} | {p['title']}" for p in pages)


class GetPageChildrenTool(_ConfluenceTool):
    name: str = "confluence_get_page_children"
    description: str = "Bir sayfanın alt sayfalarını listeler."
    class _In(BaseModel):
        page_id: str
        limit: int = 25
    args_schema: type[BaseModel] = _In

    def _run(self, page_id: str, limit: int = 25) -> str:
        children = self.confluence.get_page_child_by_type(page_id, type="page", limit=limit)
        if not children:
            return "Alt sayfa bulunamadı."
        return "\n".join(f"ID:{c['id']} | {c['title']}" for c in children)


class SearchUserTool(_ConfluenceTool):
    name: str = "confluence_search_user"
    description: str = "Confluence kullanıcısı arar."
    class _In(BaseModel):
        query: str
        limit: int = 10
    args_schema: type[BaseModel] = _In

    def _run(self, query: str, limit: int = 10) -> str:
        try:
            users = self.confluence.get_mobile_parameters(query)
            if not users:
                return "Kullanıcı bulunamadı."
            return "\n".join(
                f"{u.get('displayName','—')} | {u.get('username','—')} | {u.get('email','—')}"
                for u in users[:limit]
            )
        except Exception as e:
            return f"Hata: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# SAYFA YÖNETIMI
# ══════════════════════════════════════════════════════════════════════════════

class GetPageTool(_ConfluenceTool):
    name: str = "confluence_get_page"
    description: str = "Confluence sayfasının içeriğini getirir. ID veya başlık+space ile."
    class _In(BaseModel):
        page_id: Optional[str] = None
        title: Optional[str] = None
        space_key: Optional[str] = None
    args_schema: type[BaseModel] = _In

    def _run(self, page_id=None, title=None, space_key=None) -> str:
        if page_id:
            page = self.confluence.get_page_by_id(page_id, expand="body.storage")
        elif title and space_key:
            page = self.confluence.get_page_by_title(space_key, title, expand="body.storage")
        else:
            return "page_id veya (title + space_key) zorunlu."
        if not page:
            return "Sayfa bulunamadı."
        content = page.get("body", {}).get("storage", {}).get("value", "")
        clean   = _strip_html(content)
        url     = self.confluence.url + page.get("_links", {}).get("webui", "")
        return (
            f"ID: {page.get('id')}\n"
            f"Başlık: {page.get('title')}\n"
            f"URL: {url}\n"
            f"İçerik:\n{clean[:4000]}"
        )


class CreatePageTool(_ConfluenceTool):
    name: str = "confluence_create_page"
    description: str = (
        "Confluence'da yeni sayfa oluşturur. "
        "content HTML veya düz metin olabilir."
    )
    class _In(BaseModel):
        space_key: str
        title: str
        content: str = ""
        parent_id: Optional[str] = None
    args_schema: type[BaseModel] = _In

    def _run(self, space_key: str, title: str,
             content: str = "", parent_id=None) -> str:
        body   = _to_html(content)
        kwargs: dict = {"space": space_key, "title": title, "body": body}
        if parent_id:
            kwargs["parent_id"] = parent_id
        page = self.confluence.create_page(**kwargs)
        url  = self.confluence.url + page.get("_links", {}).get("webui", "")
        return f"Sayfa oluşturuldu: {title} (ID:{page.get('id')}) — {url}"


class UpdatePageTool(_ConfluenceTool):
    name: str = "confluence_update_page"
    description: str = "Mevcut Confluence sayfasını günceller."
    class _In(BaseModel):
        page_id: str
        title: Optional[str] = None
        content: Optional[str] = None
    args_schema: type[BaseModel] = _In

    def _run(self, page_id: str, title=None, content=None) -> str:
        page = self.confluence.get_page_by_id(page_id, expand="body.storage")
        if not page:
            return "Sayfa bulunamadı."
        new_title   = title   or page["title"]
        new_content = _to_html(content) if content else page["body"]["storage"]["value"]
        self.confluence.update_page(page_id=page_id, title=new_title, body=new_content)
        return f"Sayfa güncellendi: {new_title} (ID:{page_id})"


class DeletePageTool(_ConfluenceTool):
    name: str = "confluence_delete_page"
    description: str = "Confluence sayfasını siler. confirm=true ile onaylanmalı. GERİ ALINAMAZ!"
    class _In(BaseModel):
        page_id: str
        confirm: bool = False
    args_schema: type[BaseModel] = _In

    def _run(self, page_id: str, confirm: bool = False) -> str:
        if not confirm:
            return f"⚠️ Sayfa {page_id} silinecek. Onaylamak için confirm=true ile tekrar çağır."
        self.confluence.remove_page(page_id)
        return f"Sayfa {page_id} silindi."


# ══════════════════════════════════════════════════════════════════════════════
# YORUM & ETIKET
# ══════════════════════════════════════════════════════════════════════════════

class GetCommentsTool(_ConfluenceTool):
    name: str = "confluence_get_comments"
    description: str = "Confluence sayfasının yorumlarını getirir."
    class _In(BaseModel):
        page_id: str
    args_schema: type[BaseModel] = _In

    def _run(self, page_id: str) -> str:
        comments = self.confluence.get_page_comments(page_id).get("results", [])
        if not comments:
            return "Yorum bulunamadı."
        rows = []
        for c in comments:
            author  = c.get("history", {}).get("createdBy", {}).get("displayName", "—")
            created = c.get("history", {}).get("createdDate", "—")[:10]
            body    = _strip_html(
                c.get("body", {}).get("storage", {}).get("value", "")
            )[:200]
            rows.append(f"{author} | {created} | {body}")
        return "\n".join(rows)


class AddCommentTool(_ConfluenceTool):
    name: str = "confluence_add_comment"
    description: str = "Confluence sayfasına yorum ekler."
    class _In(BaseModel):
        page_id: str
        comment: str
    args_schema: type[BaseModel] = _In

    def _run(self, page_id: str, comment: str) -> str:
        self.confluence.add_comment(page_id, comment)
        return f"Sayfa {page_id}'e yorum eklendi."


class GetLabelsTool(_ConfluenceTool):
    name: str = "confluence_get_labels"
    description: str = "Confluence sayfasının etiketlerini getirir."
    class _In(BaseModel):
        page_id: str
    args_schema: type[BaseModel] = _In

    def _run(self, page_id: str) -> str:
        labels = self.confluence.get_page_labels(page_id).get("results", [])
        if not labels:
            return "Etiket bulunamadı."
        return ", ".join(l["name"] for l in labels)


class AddLabelTool(_ConfluenceTool):
    name: str = "confluence_add_label"
    description: str = (
        "Confluence sayfasına etiket ekler. "
        "Küçük harf, boşluksuz. Örn: 'draft', 'reviewed', 'v1.0'"
    )
    class _In(BaseModel):
        page_id: str
        label: str
    args_schema: type[BaseModel] = _In

    def _run(self, page_id: str, label: str) -> str:
        self.confluence.set_page_label(page_id, label)
        return f"'{label}' etiketi sayfa {page_id}'e eklendi."


# ══════════════════════════════════════════════════════════════════════════════
# ATTACHMENT
# ══════════════════════════════════════════════════════════════════════════════

class GetAttachmentsTool(_ConfluenceTool):
    name: str = "confluence_get_attachments"
    description: str = "Confluence sayfasının eklerini listeler."
    class _In(BaseModel):
        page_id: str
    args_schema: type[BaseModel] = _In

    def _run(self, page_id: str) -> str:
        attachments = self.confluence.get_attachments_from_content(page_id).get("results", [])
        if not attachments:
            return "Ek bulunamadı."
        return "\n".join(
            f"{a['title']} | {a.get('metadata',{}).get('mediaType','—')} | "
            f"{a.get('history',{}).get('createdDate','—')[:10]}"
            for a in attachments
        )


class UploadAttachmentTool(_ConfluenceTool):
    name: str = "confluence_upload_attachment"
    description: str = "Confluence sayfasına dosya ekler."
    class _In(BaseModel):
        page_id: str
        file_path: str
        comment: Optional[str] = None
    args_schema: type[BaseModel] = _In

    def _run(self, page_id: str, file_path: str, comment=None) -> str:
        if not os.path.exists(file_path):
            return f"Dosya bulunamadı: {file_path}"
        self.confluence.attach_file(
            file_path,
            page_id=page_id,
            comment=comment or "",
        )
        return f"{os.path.basename(file_path)} → Sayfa {page_id}'e eklendi."


# ══════════════════════════════════════════════════════════════════════════════
# JIRA BAĞLANTISI
# ══════════════════════════════════════════════════════════════════════════════

class LinkJiraIssueTool(_ConfluenceTool):
    name: str = "confluence_link_jira_issue"
    description: str = (
        "Confluence sayfasına Jira issue macro'su ekler. "
        "Sayfa ile Jira issue'sunu ilişkilendirir."
    )
    class _In(BaseModel):
        page_id: str
        jira_issue_key: str
    args_schema: type[BaseModel] = _In

    def _run(self, page_id: str, jira_issue_key: str) -> str:
        page = self.confluence.get_page_by_id(page_id, expand="body.storage")
        if not page:
            return "Sayfa bulunamadı."
        existing = page["body"]["storage"]["value"]
        macro    = (
            f'<p><ac:structured-macro ac:name="jira">'
            f'<ac:parameter ac:name="key">{jira_issue_key}</ac:parameter>'
            f'</ac:structured-macro></p>'
        )
        self.confluence.update_page(
            page_id=page_id,
            title=page["title"],
            body=existing + macro,
        )
        return f"Sayfa {page_id} ↔ {jira_issue_key} ilişkilendirildi."


# ══════════════════════════════════════════════════════════════════════════════
# FACTORY
# ══════════════════════════════════════════════════════════════════════════════

def get_all_confluence_tools(confluence: Confluence) -> list:
    """Tüm Confluence tool'larını döndürür."""
    return [
        SearchPagesTool(confluence=confluence),
        ListSpacesTool(confluence=confluence),
        ListPagesTool(confluence=confluence),
        GetPageChildrenTool(confluence=confluence),
        SearchUserTool(confluence=confluence),
        GetPageTool(confluence=confluence),
        CreatePageTool(confluence=confluence),
        UpdatePageTool(confluence=confluence),
        DeletePageTool(confluence=confluence),
        GetCommentsTool(confluence=confluence),
        AddCommentTool(confluence=confluence),
        GetLabelsTool(confluence=confluence),
        AddLabelTool(confluence=confluence),
        GetAttachmentsTool(confluence=confluence),
        UploadAttachmentTool(confluence=confluence),
        LinkJiraIssueTool(confluence=confluence),
    ]
