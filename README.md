# <img src="https://media3.giphy.com/media/v1.Y2lkPTc5MGI3NjExcHl0aWxlazRramp0a3Z5ZzI1bHIweXRrZDh0bDhvczF1dWg5YXpicCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/QDjpIL6oNCVZ4qzGs7/giphy.gif" width="50"> [Dararith J.](https://github.com/DararithJ369/DararithJ369/) — InvoiceMate

**Telegram AI Invoicing Bot for Cambodian SMEs & Freelancers**

InvoiceMate is a chat-native invoicing assistant. Businesses create, update, and manage professional invoices with embedded Bakong payment QR codes directly inside Telegram using natural language messages.

---

## Project Architecture & Core Design Rule

> **Core Design Rule:** The LLM only extracts structured data (JSON). It never writes to the database, never calculates totals, never decides invoice numbers, and never sends anything to a customer. All business logic, total calculations, and storage operations are 100% deterministic application code.

```text
InvoiceMate/
├── .env                        # Local environment variables
├── .env.example                # Template for environment configuration
├── pyproject.toml              # Dependencies & package metadata (uv)
├── main.py                     # Database initialization & seeding CLI
├── src/
│   └── invoicemate/
│       ├── api/
│       │   └── server.py       # FastAPI microservice for secure PDF downloads
│       ├── core/               # App configuration & settings (Pydantic Settings)
│       ├── db/                 # Database engine & session lifecycle (SQLite WAL + FK)
│       ├── models/             # Multi-tenant domain ORM models:
│       │   ├── org.py          # Org & OrgInvoiceCounter
│       │   ├── customer.py     # Customer (scoped by org_id, ON DELETE RESTRICT)
│       │   ├── draft.py        # Draft state machine & draft_json
│       │   ├── invoice.py      # Invoice (UniqueConstraint per org, sequential numbering)
│       │   ├── invoice_item.py # Line items with discounts & tax categories
│       │   ├── invoice_event.py# Immutable audit log
│       │   └── enums.py        # Domain lifecycle states
│       ├── schemas/            # Pydantic schemas (ExtractionPayload, DraftPayload)
│       ├── bot/                # Telegram aiogram bot & handlers
│       │   ├── bot.py          # Bot runner with RateLimitMiddleware (20 req/min/org)
│       │   ├── handlers.py     # Centralized dispatching via ConversationService
│       │   ├── card_formatter.py # Bilingual Khmer-English Telegram cards & inline buttons
│       │   └── rate_limiter.py # Per-org sliding window rate limiter
│       └── services/           # Business logic engines:
│           ├── calculator.py   # Prakas 723 compliant tax & dual-currency calculator
│           ├── conversation_service.py # Central stateful Telegram session broker
│           ├── customer_service.py # Org-scoped customer resolution & disambiguation
│           ├── exchange_rate_service.py # NBC daily API query (2s timeout) + GDT fallback
│           ├── invoice_engine.py # Draft creation, patch merge, confirmation, payment
│           ├── khmer_normalizer.py # Unicode NFKC, zero-width space & numeral normalization
│           ├── khqr_generator.py # Bakong EMVCo KHQR generator
│           ├── llm_extractor.py # Externalized prompt LLM intent extraction
│           ├── numbering.py    # Atomic row-locking sequential invoice counter
│           ├── pdf_generator.py # Bilingual ReportLab streaming PDF renderer
│           ├── storage_service.py # Unguessable token PDF storage & R2 sync
│           └── seeder.py       # Database seeder
├── scripts/
│   ├── demo_run.py             # Full end-to-end execution demo
│   └── reverse_engineer_qr.py # KHQR reverse engineering & decoder tool
└── tests/                      # Automated test suite (55 tests, 100% passing)
    ├── unit/                   # Unit test suite
    │   ├── test_phase1_models_concurrency.py # Multi-tenancy, sequences, foreign keys
    │   ├── test_phase2_business_engine.py    # Prakas 723, NBC exchange rate, PDF retry
    │   ├── test_phase3_nlp_state_manager.py  # Khmer NLP cleaning, benchmark, session state
    │   └── test_phase4_e2e_workflow.py       # E2E workflow, rate limiter, unguessable storage
    └── integration/            # Integration test suite
```

---

## Quick Start

### 1. Installation & Environment Setup

Clone the repository and install dependencies using `uv`:

```bash
uv venv
uv pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

Edit `.env`:
```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_from_botfather
GEMINI_API_KEY=your_google_gemini_api_key
LLM_PROVIDER=gemini
BAKONG_ACCOUNT_ID=your_username@aba
BASE_URL=http://localhost:8000
```

---

### 2. Initialize Database & Seed Sample Data

```bash
uv run python main.py
```

---

### 3. Run Automated Tests (55 Tests, All Passing)

```bash
uv run pytest -v
```

---

### 4. Run End-to-End Execution Demo

```bash
uv run python scripts/demo_run.py
```

---

### 5. Launch Live Telegram Bot & API Server

Start the secure PDF API server:
```bash
uv run uvicorn invoicemate.api.server:app --port 8000
```

Start the Telegram Bot:
```bash
uv run python -m invoicemate.bot.bot
```

---

## Natural Language Bot Workflow

- **Create Invoice (English or Khmer):**
  - `Invoice Sokha 2 monitors at $450 each`
  - `គិតលុយ Dara 2 monitors at $450`
- **Correct Draft:** `actually make it 3 monitors` or `add 1 keyboard for $25`
- **Confirm & Issue:** Tap `[✅ បញ្ជាក់ / Confirm]` or reply `យល់ព្រម` / `confirm` (Generates bilingual PDF + Bakong KHQR)
- **Manual Paid Toggle:** Reply `/paid INV-000001` or tap `[🟢 កត់សម្គាល់ថាបានបង់ / Mark as Paid]`
- **Search History:** `find Dara invoice` or `/invoices` or `ស្វែងរក Dara`

---

## Cambodian Fiscal Compliance (Prakas 723)

- **NBC Official Daily Exchange Rate**: Real-time integration with NBC API (hard timeout: 2000 ms), with graceful fallback to official General Department of Taxation (GDT) fallback rate (4,085 KHR/USD).
- **Dual-Currency Billing**: Subtotal, VAT (10%), PLT (5%), Accommodation Tax (2%), and Total display in both USD and KHR.
- **Auditing & Traceability**: Immutable event log (`invoice_events`) recording state transitions and exact exchange rates used at issuance.

---

## License

MIT License. Built for Cambodian SMEs and Freelancers.
