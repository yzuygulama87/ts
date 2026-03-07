# Atlassian AI Agent API

Jira ve Confluence yönetimi için FastAPI tabanlı AI Agent API.

## Özellikler

- **Jira**: Issue CRUD, batch oluşturma, worklog, attachment, issue link, epic, versiyon, board, sprint, changelog
- **Confluence**: Sayfa CRUD, arama, yorum, etiket, attachment, Jira bağlantısı
- **Agent** (`/chat`): CrewAI + vLLM (Qwen3) ile serbest metin komutları

## Kurulum

```bash
pip install -r requirements.txt
cp .env.example .env  # bilgileri doldur
uvicorn api:app --host 0.0.0.0 --port 8000
```

## Kullanım

Swagger dokümantasyonu: `http://localhost:8000/docs`

```bash
# Issue sorgula
curl -X POST http://localhost:8000/jira/search \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"jql": "project=PROJ AND status=Open"}'

# Serbest metin (agent)
curl -X POST http://localhost:8000/chat \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"message": "Bana atanmış açık issue'\''ları listele"}'
```

## Dosya Yapısı

```
├── config.py            # LLM + Jira + Confluence config
├── jira_tools.py        # 22 Jira CrewAI tool
├── confluence_tools.py  # 16 Confluence CrewAI tool
├── agent.py             # CrewAI agent factory
├── api.py               # FastAPI endpoint'leri
└── requirements.txt
```

## Stack

- **LLM**: vLLM (Qwen3)
- **Agent**: CrewAI
- **API**: FastAPI
- **Jira**: jira-python
- **Confluence**: atlassian-python-api
