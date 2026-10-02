from decimal import Decimal
import pytest

from invoicemate.models.enums import DraftState, IntentEnum, InvoiceStatus
from invoicemate.services.org_service import create_org
from invoicemate.services.customer_service import create_customer
from invoicemate.schemas.customer import CustomerCreate
from invoicemate.services.khmer_normalizer import clean_khmer_text, normalize_khmer_digits
from invoicemate.services.llm_extractor import extract_intent
from invoicemate.services.conversation_service import (
    process_incoming_message,
    process_callback_query,
    get_session_state,
)


PHASE3_BENCHMARK_PHRASES = [
    # --- 10 Create Draft phrases (English, Khmer, Mixed) ---
    {
        "phrase": "Invoice Sokha 2 monitors at $450 each",
        "draft": None,
        "expected_intent": IntentEnum.CREATE_DRAFT,
        "expected_customer": "Sokha",
    },
    {
        "phrase": "Bill Dara 10 consulting hours at $75 per hour",
        "draft": None,
        "expected_intent": IntentEnum.CREATE_DRAFT,
        "expected_customer": "Dara",
    },
    {
        "phrase": "Create invoice for Bopha Coffee 5 bags of coffee beans at $12",
        "draft": None,
        "expected_intent": IntentEnum.CREATE_DRAFT,
        "expected_customer": "Bopha Coffee",
    },
    {
        "phrase": "Invoice Vandy 1 logistics service at $150",
        "draft": None,
        "expected_intent": IntentEnum.CREATE_DRAFT,
        "expected_customer": "Vandy",
    },
    {
        "phrase": "Bill Rithy 3 desk lamps at $35 each",
        "draft": None,
        "expected_intent": IntentEnum.CREATE_DRAFT,
        "expected_customer": "Rithy",
    },
    {
        "phrase": "Invoice Chan 100000 KHR for delivery",
        "draft": None,
        "expected_intent": IntentEnum.CREATE_DRAFT,
        "expected_customer": "Chan",
    },
    {
        "phrase": "Bill Sophal 4 chairs at $50 each due in 14 days",
        "draft": None,
        "expected_intent": IntentEnum.CREATE_DRAFT,
        "expected_customer": "Sophal",
    },
    {
        "phrase": "Invoice Piseth $500 for web development",
        "draft": None,
        "expected_intent": IntentEnum.CREATE_DRAFT,
        "expected_customer": "Piseth",
    },
    # Khmer and mixed Khmer-English phrases
    {
        "phrase": "គិតលុយ Dara 2 monitors at $450",
        "draft": None,
        "expected_intent": IntentEnum.CREATE_DRAFT,
        "expected_customer": "Dara",
    },
    {
        "phrase": "Invoice Sokha ២ monitors at $450 each",  # Khmer digit ២ = 2
        "draft": None,
        "expected_intent": IntentEnum.CREATE_DRAFT,
        "expected_customer": "Sokha",
    },

    # --- 5 Update Draft phrases ---
    {
        "phrase": "actually make it 4 monitors",
        "draft": {
            "customer_name": "Sokha",
            "items": [{"name": "monitors", "quantity": 2, "unit_price": 450}],
            "currency": "USD",
        },
        "expected_intent": IntentEnum.UPDATE_DRAFT,
    },
    {
        "phrase": "change to 3",
        "draft": {
            "customer_name": "Sokha",
            "items": [{"name": "monitors", "quantity": 2, "unit_price": 450}],
            "currency": "USD",
        },
        "expected_intent": IntentEnum.UPDATE_DRAFT,
    },
    {
        "phrase": "add 1 keyboard for $25",
        "draft": {
            "customer_name": "Sokha",
            "items": [{"name": "monitors", "quantity": 2, "unit_price": 450}],
            "currency": "USD",
        },
        "expected_intent": IntentEnum.UPDATE_DRAFT,
    },
    {
        "phrase": "add 2 mouse pads for $5",
        "draft": {
            "customer_name": "Dara",
            "items": [{"name": "consulting", "quantity": 10, "unit_price": 75}],
            "currency": "USD",
        },
        "expected_intent": IntentEnum.UPDATE_DRAFT,
    },
    {
        "phrase": "ប្តូរជា 5",  # Khmer "change to 5"
        "draft": {
            "customer_name": "Sokha",
            "items": [{"name": "monitors", "quantity": 2, "unit_price": 450}],
            "currency": "USD",
        },
        "expected_intent": IntentEnum.UPDATE_DRAFT,
    },

    # --- 6 Confirm phrases (English & Khmer) ---
    {"phrase": "confirm", "draft": None, "expected_intent": IntentEnum.CONFIRM},
    {"phrase": "looks good", "draft": None, "expected_intent": IntentEnum.CONFIRM},
    {"phrase": "send it", "draft": None, "expected_intent": IntentEnum.CONFIRM},
    {"phrase": "yes", "draft": None, "expected_intent": IntentEnum.CONFIRM},
    {"phrase": "យល់ព្រម", "draft": None, "expected_intent": IntentEnum.CONFIRM},
    {"phrase": "ផ្ញើទៅ", "draft": None, "expected_intent": IntentEnum.CONFIRM},

    # --- 5 Cancel phrases (English & Khmer) ---
    {"phrase": "cancel", "draft": None, "expected_intent": IntentEnum.CANCEL},
    {"phrase": "nevermind", "draft": None, "expected_intent": IntentEnum.CANCEL},
    {"phrase": "discard", "draft": None, "expected_intent": IntentEnum.CANCEL},
    {"phrase": "បោះបង់", "draft": None, "expected_intent": IntentEnum.CANCEL},
    {"phrase": "លុបចោល", "draft": None, "expected_intent": IntentEnum.CANCEL},

    # --- 4 Search phrases (English & Khmer) ---
    {"phrase": "find Dara invoice", "draft": None, "expected_intent": IntentEnum.SEARCH},
    {"phrase": "show my invoices this week", "draft": None, "expected_intent": IntentEnum.SEARCH},
    {"phrase": "search for Sokha", "draft": None, "expected_intent": IntentEnum.SEARCH},
    {"phrase": "ស្វែងរក Dara", "draft": None, "expected_intent": IntentEnum.SEARCH},

    # --- 2 Clarify Needed phrases ---
    {"phrase": "bill someone $50", "draft": None, "expected_intent": IntentEnum.CLARIFY_NEEDED},
    {"phrase": "invoice Sokha", "draft": None, "expected_intent": IntentEnum.CLARIFY_NEEDED},
]


def test_khmer_orthographic_cleaning():
    """Verify zero-width space removal and Khmer digit normalization."""
    raw = "សួស្ដី\u200bកម្ពុជា ១២៣"
    cleaned = clean_khmer_text(raw)
    assert "\u200b" not in cleaned
    assert "123" in cleaned  # Khmer 123 normalized


def test_bilingual_nlp_benchmark_accuracy():
    """
    Phase 3 Validation Gate:
    Proves bilingual NLP parsing achieves >= 90% accuracy on standardized benchmark set.
    """
    total = len(PHASE3_BENCHMARK_PHRASES)
    assert total >= 30, f"Benchmark suite should contain at least 30 phrases, got {total}"

    passed = 0
    for idx, case in enumerate(PHASE3_BENCHMARK_PHRASES, 1):
        phrase = case["phrase"]
        expected = case["expected_intent"]
        draft = case.get("draft")

        res = extract_intent(phrase, current_draft=draft)
        if res.intent == expected:
            passed += 1
        else:
            print(f"Failed case #{idx}: phrase='{phrase}' expected={expected} got={res.intent}")

    accuracy = (passed / total) * 100
    print(f"\nPhase 3 Benchmark Accuracy: {accuracy:.2f}% ({passed}/{total})")
    assert accuracy >= 90.0, f"Extraction accuracy target (>=90%) failed: got {accuracy:.2f}%"


def test_state_machine_workflow_and_callbacks(db_session):
    """
    Phase 3 Validation:
    Verify state machine lifecycle:
    IDLE -> CREATE_DRAFT -> WAITING_FOR_CONFIRMATION -> UPDATE_DRAFT -> CONFIRM -> SENT
    and inline callbacks.
    """
    org = create_org(db_session, telegram_user_id="tg_conv_state_user")
    chat_id = "chat_sm_1"

    # Step 1: IDLE state
    state, draft = get_session_state(db_session, org_id=org.id, chat_id=chat_id)
    assert state == DraftState.IDLE.value
    assert draft is None

    # Step 2: User says "Invoice Sokha 2 monitors at $450 each"
    res1 = process_incoming_message(
        db_session,
        org_id=org.id,
        chat_id=chat_id,
        message_text="Invoice Sokha 2 monitors at $450 each",
    )
    assert res1["action"] == "draft_created"
    assert res1["state"] == DraftState.WAITING_FOR_CONFIRMATION.value
    active_draft = res1["draft"]
    assert active_draft.draft_json["subtotal"] == 900.00

    # Step 3: User says "actually make it 3 monitors"
    res2 = process_incoming_message(
        db_session,
        org_id=org.id,
        chat_id=chat_id,
        message_text="actually make it 3 monitors",
    )
    assert res2["action"] == "draft_updated"
    assert res2["state"] == DraftState.WAITING_FOR_CONFIRMATION.value
    updated_draft = res2["draft"]
    assert updated_draft.draft_json["subtotal"] == 1350.00

    # Step 4: User taps "Confirm" callback button
    res3 = process_callback_query(
        db_session,
        org_id=org.id,
        chat_id=chat_id,
        callback_data=f"cb_confirm_draft:{updated_draft.id}",
    )
    assert res3["action"] == "invoice_confirmed"
    assert res3["state"] == DraftState.SENT.value
    inv = res3["invoice"]
    assert inv.invoice_number == "INV-000001"
    assert inv.status == InvoiceStatus.SENT.value

    # Step 5: Mark paid callback
    res4 = process_callback_query(
        db_session,
        org_id=org.id,
        chat_id=chat_id,
        callback_data=f"mark_paid:{inv.id}",
    )
    assert res4["action"] == "marked_paid"
    assert res4["state"] == DraftState.PAID.value


def test_customer_disambiguation_state(db_session):
    """
    Phase 3 Validation:
    Verify when multiple customers match, state transitions to WAITING_FOR_CUSTOMER_SELECTION,
    and user selecting a customer resolves the draft.
    """
    org = create_org(db_session, telegram_user_id="tg_disambig_user")
    chat_id = "chat_sm_disambig"

    # Pre-create 2 matching customers
    c1 = create_customer(db_session, org_id=org.id, customer_in=CustomerCreate(name="Dara Trading"))
    c2 = create_customer(db_session, org_id=org.id, customer_in=CustomerCreate(name="Dara Electronics"))

    # User says "Invoice Dara 1 laptop for $800"
    res = process_incoming_message(
        db_session,
        org_id=org.id,
        chat_id=chat_id,
        message_text="Invoice Dara 1 laptop for $800",
    )
    assert res["action"] == "customer_disambiguation_required"
    assert res["state"] == DraftState.WAITING_FOR_CUSTOMER_SELECTION.value
    assert len(res["matches"]) == 2

    # User taps callback for c1
    res_select = process_callback_query(
        db_session,
        org_id=org.id,
        chat_id=chat_id,
        callback_data=f"select_cust:{c1.id}",
    )
    assert res_select["action"] == "draft_updated"
    assert res_select["state"] == DraftState.WAITING_FOR_CONFIRMATION.value
    assert res_select["draft"].customer_id == c1.id
