import os
from dotenv import load_dotenv
from pydantic import BaseModel

# Load environment variables from .env file
load_dotenv()


class Settings(BaseModel):
    PROJECT_NAME: str = "InvoiceMate"
    VERSION: str = "0.1.0"
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./invoicemate.db")
    SQL_ECHO: bool = os.getenv("SQL_ECHO", "0") == "1"
    
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini").lower()

    BAKONG_ACCOUNT_ID: str = os.getenv("BAKONG_ACCOUNT_ID", "invoicemate@bakong")
    DEFAULT_CURRENCY: str = os.getenv("DEFAULT_CURRENCY", "USD")
    INVOICE_PREFIX: str = os.getenv("INVOICE_PREFIX", "INV-")
    INVOICE_PADDING: int = int(os.getenv("INVOICE_PADDING", "6"))
    STORAGE_DIR: str = os.getenv("STORAGE_DIR", "./storage/invoices")
    HYBRID_INTENT_MODEL: str = os.getenv("HYBRID_INTENT_MODEL", "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli")
    GLINER_MODEL_NAME: str = os.getenv("GLINER_MODEL_NAME", "urchade/gliner_multi-v2.1")
    INTENT_DATASET_PATH: str = os.getenv("INTENT_DATASET_PATH", "data/intent_dataset.jsonl")

    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    BASE_URL: str = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")


settings = Settings()
