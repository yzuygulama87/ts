"""
agent.py
────────
CrewAI agent factory. Tüm Jira ve Confluence tool'larını kullanır.
"""

import os
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from crewai import Agent, Crew, LLM, Process, Task
from jira import JIRA
from atlassian import Confluence

from jira_tools import get_all_jira_tools
from confluence_tools import get_all_confluence_tools


@dataclass
class LogEntry:
    ts: str
    msg: str
    level: str


@dataclass
class AgentResult:
    output: str
    logs: list[LogEntry] = field(default_factory=list)
    success: bool = True


def run_agent(
    user_input: str,
    jira: JIRA,
    llm: LLM,
    confluence: Optional[Confluence] = None,
) -> AgentResult:
    logs: list[LogEntry] = []

    def log(msg: str, level: str = "info") -> None:
        logs.append(LogEntry(ts=datetime.now().strftime("%H:%M:%S"), msg=msg, level=level))

    try:
        tools = get_all_jira_tools(jira)
        if confluence:
            tools += get_all_confluence_tools(confluence)

        log(f"{len(tools)} araç yüklendi", "ok")

        agent = Agent(
            role="Atlassian Project Manager",
            goal=(
                "Jira ve Confluence projelerini etkin yönet. "
                "Issue yönetimi, sprint planlama, worklog takibi, "
                "Confluence dokümantasyonu ve Jira-Confluence entegrasyonu."
            ),
            backstory=(
                "Deneyimli bir Atlassian uzmanısın. "
                "Jira Server ve Confluence Server kurulumlarıyla çalışıyorsun. "
                "Türkçe veya İngilizce yanıt verebilirsin."
            ),
            tools=tools,
            llm=llm,
            verbose=False,
            max_iter=20,
        )

        task = Task(
            description=user_input,
            expected_output=(
                "Yapılan işlemlerin özeti, sonuçları ve ilgili linkler"
            ),
            agent=agent,
        )

        log("Agent çalışıyor...", "info")
        crew = Crew(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=False,
        )
        result = crew.kickoff()
        log("Tamamlandı", "ok")
        return AgentResult(output=str(result), logs=logs)

    except Exception as exc:
        log(f"Hata: {exc}", "err")
        return AgentResult(output=f"❌ {exc}", logs=logs, success=False)
