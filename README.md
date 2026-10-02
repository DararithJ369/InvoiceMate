# <img src="https://media3.giphy.com/media/v1.Y2lkPTc5MGI3NjExcHl0aWxlazRramp0a3Z5ZzI1bHIweXRrZDh0bDhvczF1dWg5YXpicCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/QDjpIL6oNCVZ4qzGs7/giphy.gif" width="50"> [Dararith J.](https://github.com/DararithJ369/DararithJ369/) — InvoiceMate

**Telegram AI Invoicing Bot for Cambodian SMEs & Freelancers**

InvoiceMate is a chat-native invoicing assistant. Businesses create, update, and manage professional invoices with embedded Bakong payment KHQR codes directly inside Telegram using natural language messages in English and Khmer.

---

## Architecture & Core Design Rule

> **Core Design Rule:** The LLM strictly extracts structured JSON. All business calculations, sequential invoice numbering, database operations, and state transitions are 100% deterministic application code.

```text
InvoiceMate/
├── src/invoicemate/
│   ├── api/          # FastAPI PDF download service
│   ├── bot/          # Telegram bot handlers & rate limiter
│   ├── core/         # App configuration & settings
│   ├── db/           # SQLite WAL database & session lifecycle
│   ├── models/       # Multi-tenant ORM models
│   ├── schemas/      # Pydantic validation schemas
│   └── services/     # Tax calculator, KHQR generator, PDF renderer & NLP
├── tests/            # Automated test suite (60 unit tests)
├── scripts/          # Demos & utility scripts
└── main.py           # Database initialization & seeding CLI
```

---

## Quick Start

### 1. Installation & Environment Setup

Clone the repository and install dependencies using `uv`:

```bash
uv venv
uv pip install -e ".[dev]"
```

Configure `.env`:

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

### 3. Run Automated Tests

```bash
uv run pytest -v
```

---

### 4. Run Execution Demo

```bash
uv run python scripts/demo_run.py
```

---

### 5. Launch Live Bot & API Server

Start the PDF download service:
```bash
uv run uvicorn invoicemate.api.server:app --port 8000
```

Start the Telegram Bot:
```bash
uv run python -m invoicemate.bot.bot
```

---

## Bot Commands & Natural Language Workflow

- **Create Invoice (English / Khmer):**
  - `Invoice Sokha 2 monitors at $450 each`
  - `គិតលុយ Dara: 1 laptop $800, 1 mouse $25`
- **Modify Draft:** `actually make it 3 monitors` or `add 1 keyboard for $25`
- **Confirm & Issue:** Tap `[✅ បញ្ជាក់ / Confirm]` or send `confirm` / `យល់ព្រម` (Generates bilingual PDF with Bakong KHQR)
- **Mark as Paid:** Reply `/paid [INV-NUMBER]` or tap `[🟢 កត់សម្គាល់ថាបានបង់ / Mark as Paid]`
- **Search History:** `find Dara invoice` or `/invoices` or `ស្វែងរក Dara`
- **Clear Draft:** `/clear` or `cancel`

---

## Cambodian Fiscal Compliance (Prakas 723)

- **NBC Official Daily Exchange Rate**: Real-time integration with NBC API (hard timeout: 2000 ms), with graceful fallback to official General Department of Taxation (GDT) fallback rate (4,085 KHR/USD).
- **Dual-Currency Billing**: Subtotal, VAT (10%), PLT (5%), Accommodation Tax (2%), and Total display in both USD and KHR.

---

## License

MIT License. Built for Cambodian SMEs and Freelancers.
