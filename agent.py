"""
agent.py
--------
fast  -> direkt litellm tool calling (~2 LLM cagrisi, hizli)
smart -> CrewAI agent (cok adimli karmasik gorevler icin)
"""

import os

# CrewAI 1.9.3 OPENAI_API_BASE env var'ından base_url okur
# Bu satırlar her iki modda da çalışması için burada set ediliyor
os.environ.setdefault("OPENAI_API_KEY",  "dummy")
os.environ.setdefault("OPENAI_BASE_URL", "http://sinerjicuda02:8010/v1")
os.environ.setdefault("OPENAI_API_BASE", "http://sinerjicuda02:8010/v1")
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Literal

import litellm
from jira import JIRA
from atlassian import Confluence

from jira_tools import get_all_jira_tools
from confluence_tools import get_all_confluence_tools

os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"
litellm.drop_params = True


@dataclass
class LogEntry:
    ts: str
    msg: str
    level: str


@dataclass
class AgentResult:
    output: str
    logs: list = field(default_factory=list)
    success: bool = True
    mode: str = "fast"


def _tool_to_schema(tool) -> dict:
    schema = tool.args_schema.model_json_schema()
    return {
        "type": "function",
        "function": {
            "name": tool.name.replace("-", "_"),
            "description": tool.description,
            "parameters": {
                "type": "object",
                "properties": schema.get("properties", {}),
                "required": schema.get("required", []),
            },
        },
    }


# ─────────────────────────────────────────────────────────────────────
# FAST MODE
# ─────────────────────────────────────────────────────────────────────

# ── Tool gruplari ──────────────────────────────────────────────────────────
JIRA_READ  = {"jira_search_issues","jira_get_issue","jira_get_all_projects",
              "jira_get_project_issues","jira_get_transitions","jira_search_fields",
              "jira_get_user_profile","jira_get_changelog"}
JIRA_WRITE = {"jira_create_issue","jira_batch_create_issues","jira_update_issue",
              "jira_transition_issue","jira_delete_issue","jira_add_comment",
              "jira_manage_worklog","jira_manage_attachment","jira_manage_issue_link",
              "jira_link_to_epic","jira_manage_version"}
JIRA_AGILE = {"jira_get_agile_boards","jira_get_board_issues","jira_manage_sprint","jira_get_sprint_issues_by_name"}
CF_ALL     = {"confluence_search","confluence_list_spaces","confluence_list_pages",
              "confluence_get_page_children","confluence_search_user",
              "confluence_get_page","confluence_create_page","confluence_update_page",
              "confluence_delete_page","confluence_get_comments","confluence_add_comment",
              "confluence_get_labels","confluence_add_label","confluence_get_attachments",
              "confluence_upload_attachment","confluence_link_jira_issue"}


def _route_tools(user_input: str, all_tools: list) -> list:
    """Mesaja bakarak sadece ilgili tool grubunu secip gonderir.
    38 yerine 5-12 tool = 4-6x daha az token = cok daha hizli."""
    text = user_input.lower()
    cf_kw    = ["confluence","sayfa","page","space","dokuman","wiki","blog","label","etiket"]
    agile_kw = ["sprint","board","agile","scrum"]
    write_kw = ["oluştur","olustur","create","ekle","add","güncelle","guncelle","update",
                "sil","delete","kapat","close","yorum","comment","worklog","attach",
                "link","epic","versiyon","version","tasi","taşı","move","ata","assign"]

    want_cf    = any(k in text for k in cf_kw)
    want_agile = any(k in text for k in agile_kw)
    want_write = any(k in text for k in write_kw)

    allowed = set(JIRA_READ)
    if want_write:  allowed |= JIRA_WRITE
    if want_agile:  allowed |= JIRA_AGILE
    if want_cf:     allowed |= CF_ALL

    filtered = [t for t in all_tools if t.name.replace("-","_") in allowed]
    return filtered if filtered else all_tools


def _run_fast(user_input, jira, llm_model, confluence, max_rounds, logs):
    def log(msg, level="info"):
        logs.append(LogEntry(ts=datetime.now().strftime("%H:%M:%S"), msg=msg, level=level))

    all_tools = get_all_jira_tools(jira)
    if confluence:
        all_tools += get_all_confluence_tools(confluence)

    tools    = _route_tools(user_input, all_tools)
    tool_map = {t.name.replace("-", "_"): t for t in all_tools}  # calistirmak icin tumu
    schemas  = [_tool_to_schema(t) for t in tools]
    log(f"{len(tools)}/{len(all_tools)} arac secildi (fast mode)", "ok")

    messages = [
        {
            "role": "system",
            "content": (
                "Sen bir Atlassian uzmanisisin. Jira ve Confluence'i yonetiyorsun. "
                "Kullanicinin istegini yerine getirmek icin uygun tool'lari kullan. "
                "Turkce veya Ingilizce yanit verebilirsin. "
                "Islemi tamamladiktan sonra kisa ve net bir ozet yaz."
            ),
        },
        {"role": "user", "content": user_input},
    ]

    model = f"openai/{llm_model}"

    for round_num in range(max_rounds):
        log(f"LLM cagrisi #{round_num + 1}", "info")
        response = litellm.completion(
            model=model, messages=messages, tools=schemas,
            tool_choice="auto", api_key="dummy", max_tokens=2048, temperature=0.3,
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            log("Tamamlandi", "ok")
            return AgentResult(output=msg.content or "Islem tamamlandi.", logs=logs, mode="fast")

        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
        })

        for tc in msg.tool_calls:
            tool_name = tc.function.name
            tool_args = json.loads(tc.function.arguments)
            log(f"Tool: {tool_name}", "info")
            tool = tool_map.get(tool_name)
            if not tool:
                result = f"Tool bulunamadi: {tool_name}"
            else:
                try:
                    result = tool._run(**tool_args)
                except Exception as e:
                    result = f"Tool hatasi: {e}"
            log(f"  -> {str(result)[:80]}", "ok")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})

    response = litellm.completion(
        model=model, messages=messages, api_key="dummy", max_tokens=1024, temperature=0.3,
    )
    log("Tamamlandi", "ok")
    return AgentResult(
        output=response.choices[0].message.content or "Islem tamamlandi.",
        logs=logs, mode="fast"
    )


# ─────────────────────────────────────────────────────────────────────
# SMART MODE
# ─────────────────────────────────────────────────────────────────────

def _run_smart(user_input, jira, llm_model, confluence, logs):
    def log(msg, level="info"):
        logs.append(LogEntry(ts=datetime.now().strftime("%H:%M:%S"), msg=msg, level=level))

    try:
        from crewai import Agent, Crew, LLM, Process, Task
        from crewai.tools import BaseTool as CrewBaseTool
        from pydantic import BaseModel
    except ImportError:
        log("crewai kurulu degil. pip install crewai", "err")
        return AgentResult(
            output="smart mod icin crewai gerekli. `pip install crewai` calistir.",
            logs=logs, success=False, mode="smart",
        )

    tools = get_all_jira_tools(jira)
    if confluence:
        tools += get_all_confluence_tools(confluence)
    log(f"{len(tools)} arac yuklendi (smart mode)", "ok")

    # CrewAI 1.9.3: model adında openai/ prefix olmadan,
    # OPENAI_API_BASE env var'ından base_url okur
    llm = LLM(
        model=llm_model,
        api_key="dummy",
        temperature=0.3,
        max_tokens=4096,
    )

    def _make_crewai_tool(inner, schema):
        """Closure bug'unu önlemek için factory fonksiyon."""
        class _W(CrewBaseTool):
            name: str = inner.name
            description: str = inner.description
            args_schema = schema

            def _run(self, **kwargs) -> str:
                return inner._run(**kwargs)

        _W.__name__ = f"_W_{inner.name}"
        return _W()

    crewai_tools = [_make_crewai_tool(t, t.args_schema) for t in tools]

    agent = Agent(
        role="Atlassian Project Manager",
        goal=(
            "Jira ve Confluence projelerini etkin yonet. "
            "Karmasik cok adimli gorevleri planlayarak uygula."
        ),
        backstory=(
            "Deneyimli bir Atlassian uzmanisisin. "
            "Turkce veya Ingilizce yanit verebilirsin."
        ),
        tools=crewai_tools,
        llm=llm,
        verbose=False,
        max_iter=15,
    )

    task = Task(
        description=user_input,
        expected_output="Yapilan islemlerin ozeti, sonuclari ve ilgili linkler",
        agent=agent,
    )

    log("Agent calisiyor...", "info")
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
    result = crew.kickoff()
    log("Tamamlandi", "ok")
    return AgentResult(output=str(result), logs=logs, mode="smart")


# ─────────────────────────────────────────────────────────────────────
# ANA FONKSİYON
# ─────────────────────────────────────────────────────────────────────

def run_agent(
    user_input: str,
    jira: JIRA,
    llm_model: str,
    confluence: Optional[Confluence] = None,
    mode: str = "fast",
    max_rounds: int = 6,
) -> AgentResult:
    logs = []

    def log(msg, level="info"):
        logs.append(LogEntry(ts=datetime.now().strftime("%H:%M:%S"), msg=msg, level=level))

    try:
        if mode == "smart":
            return _run_smart(user_input, jira, llm_model, confluence, logs)
        else:
            return _run_fast(user_input, jira, llm_model, confluence, max_rounds, logs)
    except Exception as exc:
        log(f"Hata: {exc}", "err")
        return AgentResult(output=f"Hata: {exc}", logs=logs, success=False, mode=mode)
