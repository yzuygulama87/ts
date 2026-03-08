"""
agent.py
--------
fast  -> direkt litellm tool calling (~2 LLM cagrisi, hizli)
smart -> CrewAI agent (cok adimli karmasik gorevler icin)
"""

import os
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

def _run_fast(user_input, jira, llm_model, confluence, max_rounds, logs):
    def log(msg, level="info"):
        logs.append(LogEntry(ts=datetime.now().strftime("%H:%M:%S"), msg=msg, level=level))

    tools = get_all_jira_tools(jira)
    if confluence:
        tools += get_all_confluence_tools(confluence)

    tool_map = {t.name.replace("-", "_"): t for t in tools}
    schemas  = [_tool_to_schema(t) for t in tools]
    log(f"{len(tools)} arac yuklendi (fast mode)", "ok")

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

    llm = LLM(
        model=f"openai/{llm_model}",
        api_key="dummy",
        temperature=0.3,
        max_tokens=4096,
    )

    crewai_tools = []
    for t in tools:
        _inner  = t
        _schema = t.args_schema

        class _W(CrewBaseTool):
            name: str = _inner.name
            description: str = _inner.description
            args_schema = _schema

            def _run(self, **kwargs) -> str:
                return _inner._run(**kwargs)

        crewai_tools.append(_W())

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
