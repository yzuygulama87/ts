"""
agent.py
────────
CrewAI yerine direkt litellm tool calling kullanır.
Çok daha hızlı: 6 LLM çağrısı yerine 2 çağrı.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import litellm
from jira import JIRA
from atlassian import Confluence

from jira_tools import get_all_jira_tools
from confluence_tools import get_all_confluence_tools

litellm.drop_params = True


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


def run_agent(
    user_input: str,
    jira: JIRA,
    llm_model: str,
    confluence: Optional[Confluence] = None,
    max_rounds: int = 6,
) -> AgentResult:
    logs: list[LogEntry] = []

    def log(msg: str, level: str = "info") -> None:
        logs.append(LogEntry(ts=datetime.now().strftime("%H:%M:%S"), msg=msg, level=level))

    try:
        tools    = get_all_jira_tools(jira)
        if confluence:
            tools += get_all_confluence_tools(confluence)

        tool_map = {t.name.replace("-", "_"): t for t in tools}
        schemas  = [_tool_to_schema(t) for t in tools]
        log(f"{len(tools)} araç yüklendi", "ok")

        messages = [
            {
                "role": "system",
                "content": (
                    "Sen bir Atlassian uzmanısın. Jira ve Confluence'ı yönetiyorsun. "
                    "Kullanıcının isteğini yerine getirmek için uygun tool'ları kullan. "
                    "Türkçe veya İngilizce yanıt verebilirsin. "
                    "İşlemi tamamladıktan sonra kısa ve net bir özet yaz."
                ),
            },
            {"role": "user", "content": user_input},
        ]

        model = f"openai/{llm_model}"

        for round_num in range(max_rounds):
            log(f"LLM çağrısı #{round_num + 1}", "info")

            response = litellm.completion(
                model=model,
                messages=messages,
                tools=schemas,
                tool_choice="auto",
                api_key="dummy",
                max_tokens=2048,
                temperature=0.3,
            )

            msg = response.choices[0].message

            if not msg.tool_calls:
                output = msg.content or "İşlem tamamlandı."
                log("Tamamlandı", "ok")
                return AgentResult(output=output, logs=logs)

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
                    result = f"Tool bulunamadı: {tool_name}"
                else:
                    try:
                        result = tool._run(**tool_args)
                    except Exception as e:
                        result = f"Tool hatası: {e}"

                log(f"  → {str(result)[:80]}", "ok")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": str(result),
                })

        # max_rounds doldu
        response = litellm.completion(
            model=model,
            messages=messages,
            api_key="dummy",
            max_tokens=1024,
            temperature=0.3,
        )
        output = response.choices[0].message.content or "İşlem tamamlandı."
        log("Tamamlandı", "ok")
        return AgentResult(output=output, logs=logs)

    except Exception as exc:
        log(f"Hata: {exc}", "err")
        return AgentResult(output=f"❌ {exc}", logs=logs, success=False)
