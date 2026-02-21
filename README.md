# Relay

AI Emergency Response System — Automated ePCR for Paramedics.

Relay captures real-time audio from paramedics, transcribes it, and extracts structured NEMSIS v3.5 medical data using LLMs. It enriches patient records by querying FHIR health information exchanges and contacting GPs, then streams everything to a hospital dashboard for live monitoring.

## Architecture

```
Paramedic (audio) ──WebSocket──▶ Transcription ──▶ NEMSIS Extraction (Claude)
                                                          │
                                          ┌───────────────┼───────────────┐
                                          ▼               ▼               ▼
                                    FHIR Lookup     GP Caller       Medical DB
                                          │          (Twilio +        │
                                          │         ElevenLabs)       │
                                          ▼               ▼           ▼
                                     Clinical Insights + Alerts
                                              │
                                        Event Bus (Pub/Sub)
                                              │
                                              ▼
                                    Hospital Dashboard (WebSocket)
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys (at minimum ANTHROPIC_API_KEY)

# Run
uvicorn app.main:app --reload
```

- Paramedic UI: http://localhost:8000/
- Hospital Dashboard: http://localhost:8000/hospital

## Key Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Claude API key for NEMSIS extraction | required |
| `ELEVENLABS_API_KEY` | Voice agent for GP calls | optional |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | Outbound calling | optional |
| `LLM_PROVIDER` | `auto`, `anthropic`, or `openai` | `auto` |
| `DATABASE_URL` | PostgreSQL connection string for production | SQLite default |
| `SEED_DEMO_CASES` | Populate demo cases on startup | `true` |
| `GP_CALLS_ENABLED` | Enable outbound GP calls | `false` |
| `DUMMY_MODE` | Mock data generation for development | `false` |
| `GCP_PROJECT_ID` / `GCP_PUBSUB_TOPIC` | Multi-instance event streaming | optional |

See `.env.example` for the full list.

## Project Structure

```
app/
  main.py              # FastAPI app entrypoint
  config.py            # Environment configuration
  database.py          # SQLite / PostgreSQL abstraction
  routers/
    stream.py          # WebSocket audio streaming + transcription
    cases.py           # REST API for case CRUD
    hospital.py        # Hospital dashboard WebSocket
    gp_call.py         # GP call workflow endpoints
  services/
    nemsis_extractor.py  # Transcript → NEMSIS v3.5 via LLM
    llm.py               # LLM abstraction (Anthropic / OpenAI)
    transcription.py     # Real-time audio transcription
    voice_agent.py       # ElevenLabs + Twilio voice calling
    fhir_client.py       # FHIR R4 patient record queries
    gp_caller.py         # GP contact workflow
    gp_documents.py      # PDF/OCR extraction of GP records
    gp_lookup.py         # GP practice phone lookup
    clinical_insights.py # Clinical alerts and recommendations
    medical_db.py        # Medical history queries
    event_bus.py         # Pub/Sub or in-memory event streaming
  models/
    nemsis.py          # NEMSIS v3.5 data structures
    case.py            # Case API models
    clinical.py        # Clinical decision support models
    transcript.py      # Transcript segment models
static/                # Frontend UIs (paramedic + hospital)
docs/                  # Deployment guides
tests/                 # pytest test suite
```

## Testing

```bash
pytest
```

Requires 60% minimum code coverage. Config in `pyproject.toml`.

## Deployment

See [`docs/gcp-setup.md`](docs/gcp-setup.md) for Cloud Run deployment with Cloud SQL and Pub/Sub.

## Tech Stack

- **Backend**: FastAPI, WebSockets, Pydantic
- **AI**: Anthropic Claude, OpenAI (fallback), ElevenLabs
- **Healthcare**: FHIR R4, NEMSIS v3.5
- **Database**: SQLite (dev) / PostgreSQL (prod)
- **Telephony**: Twilio
- **Cloud**: GCP Cloud Run, Pub/Sub, Cloud SQL
- **Python**: 3.11+
