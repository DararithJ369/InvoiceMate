import enum


class InvoiceStatus(str, enum.Enum):
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"
    CANCELLED = "cancelled"


class DraftState(str, enum.Enum):
    IDLE = "IDLE"
    DRAFTING = "DRAFTING"
    WAITING_FOR_CUSTOMER_SELECTION = "WAITING_FOR_CUSTOMER_SELECTION"
    WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    GENERATING_PDF = "GENERATING_PDF"
    PDF_READY = "PDF_READY"
    PDF_FAILED = "PDF_FAILED"
    SENT = "SENT"
    PAID = "PAID"


class PdfStatus(str, enum.Enum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class EventType(str, enum.Enum):
    CREATED = "created"
    EDITED = "edited"
    CONFIRMED = "confirmed"
    PDF_FAILED = "pdf_failed"
    MARKED_PAID = "marked_paid"


class IntentEnum(str, enum.Enum):
    CREATE_DRAFT = "create_draft"
    UPDATE_DRAFT = "update_draft"
    CONFIRM = "confirm"
    CANCEL = "cancel"
    SEARCH = "search"
    SELECT_CUSTOMER = "select_customer"
    CLARIFY_NEEDED = "clarify_needed"
    GREETING = "greeting"
    THANKS = "thanks"
    HELP = "help"
