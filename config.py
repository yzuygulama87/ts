import os
from dataclasses import dataclass
from crewai import LLM
from jira import JIRA
from atlassian import Confluence


@dataclass
class LLMConfig:
    base_url: str = "http://sinerjicuda02:8010/v1"
    model_name: str = "Qwen/Qwen3-VL-8B-Thinking"
    temperature: float = 0.3

    def build(self) -> LLM:
        return LLM(
            model=self.model_name,
            api_key="dummy",
            temperature=self.temperature,
            max_tokens=4096,
        )


@dataclass
class JiraConfig:
    server: str = ""
    email: str = ""
    token: str = ""

    def build(self) -> JIRA:
        client = JIRA(server=self.server, basic_auth=(self.email, self.token))
        client.projects()
        return client

    def is_filled(self) -> bool:
        return bool(self.server and self.email and self.token)


@dataclass
class ConfluenceConfig:
    server: str = ""
    email: str = ""
    token: str = ""

    def build(self) -> Confluence:
        return Confluence(url=self.server, username=self.email, password=self.token)

    def is_filled(self) -> bool:
        return bool(self.server and self.email and self.token)
