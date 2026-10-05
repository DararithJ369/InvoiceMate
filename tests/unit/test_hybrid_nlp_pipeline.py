import json
import os
import pytest
from decimal import Decimal

from invoicemate.models.enums import IntentEnum, DraftState
from invoicemate.services.khmer_normalizer import segment_khmer_text, clean_khmer_text
from invoicemate.services.hybrid_extractor import (
    HybridNLPExtractor,
    detect_language,
    log_interaction_to_dataset,
)
from invoicemate.services.conversation_service import (
    process_incoming_message,
    get_session_state,
)
from invoicemate.services.org_service import get_or_create_org


def test_khmer_preprocessing_and_segmentation():
    """Verify clean_khmer_text and khmer-nltk segmentation."""
    raw = "ធ្វើ invoice ឲ្យ Dara $50 សម្រាប់ website design"
    segmented = segment_khmer_text(raw)
    assert isinstance(segmented, str)
    assert len(segmented) >= len(raw)
    assert "Dara" in segmented
    assert "50" in segmented


def test_language_detection():
    assert detect_language("Invoice Sokha 2 monitors at $450") == "en"
    assert detect_language("យល់ព្រម") == "km"
    assert detect_language("ធ្វើ invoice ឲ្យ Dara $50") == "mixed"


def test_hybrid_extractor_live_inference():
    """
    Test live Track A inference for mixed Khmer-English commercial text.
    Verifies confidence >= 0.75 gate and correct extraction.
    """
    # 1. Create Draft
    msg = "ធ្វើ invoice ឲ្យ Dara $50 សម្រាប់ website design"
    res = HybridNLPExtractor.extract(msg)
    assert res.intent == IntentEnum.CREATE_DRAFT
    assert res.confidence >= 0.75
    assert res.customer_name == "Dara"
    assert len(res.items) >= 1
    assert res.items[0].unit_price == Decimal("50.0")

    # 2. Update Draft
    draft_ctx = {
        "customer_name": "Dara",
        "items": [{"name": "website design", "qty": 1.0, "unit_price": 50.0}],
    }
    msg_update = "actually make it 2 website design"
    res_update = HybridNLPExtractor.extract(msg_update, current_draft=draft_ctx)
    assert res_update.intent == IntentEnum.UPDATE_DRAFT
    assert res_update.confidence >= 0.75

    # 3. Confirm (Khmer)
    res_confirm = HybridNLPExtractor.extract("យល់ព្រម")
    assert res_confirm.intent == IntentEnum.CONFIRM
    assert res_confirm.confidence >= 0.75

    # 4. Cancel (Khmer)
    res_cancel = HybridNLPExtractor.extract("បោះបង់")
    assert res_cancel.intent == IntentEnum.CANCEL
    assert res_cancel.confidence >= 0.75

    # 5. Search
    res_search = HybridNLPExtractor.extract("find Dara invoice")
    assert res_search.intent == IntentEnum.SEARCH
    assert res_search.confidence >= 0.75


def test_hybrid_state_machine_transition(db_session):
    """
    Verify that incoming mixed Khmer-English message triggers
    IDLE -> DRAFTING state transition in ConversationService using hybrid provider.
    """
    chat_id = "99912388"
    db = db_session
    org = get_or_create_org(db, telegram_user_id="user_test_999")
    org_id = org.id

    # Initial state should be IDLE
    state_before, draft_before = get_session_state(db, org_id=org_id, chat_id=chat_id)
    assert state_before == DraftState.IDLE.value

    # Send mixed Khmer-English invoice request with provider='hybrid'
    incoming_text = "ធ្វើ invoice ឲ្យ Dara $50 សម្រាប់ website design"
    resp = process_incoming_message(
        db=db,
        org_id=org_id,
        chat_id=chat_id,
        message_text=incoming_text,
        provider="hybrid",
    )

    # Check action & updated state
    assert resp["action"] in ["draft_created", "draft_updated", "customer_disambiguation_needed", "draft_disambiguation_needed"]
    state_after, draft_after = get_session_state(db, org_id=org_id, chat_id=chat_id)
    assert state_after in [DraftState.WAITING_FOR_CONFIRMATION.value, DraftState.DRAFTING.value]
    assert draft_after is not None
    assert draft_after.draft_json is not None
    assert "Dara" in str(draft_after.draft_json)


def test_interaction_logging_to_dataset(tmp_path):
    """Verify that interaction is logged directly to jsonl dataset."""
    test_jsonl = tmp_path / "test_intent_dataset.jsonl"
    msg = "ធ្វើ invoice ឲ្យ Sokha $100 សម្រាប់ consulting"

    # Call extractor with custom logging path
    res = HybridNLPExtractor.extract(msg)
    log_interaction_to_dataset(
        text=msg,
        intent=res.intent,
        confidence=res.confidence,
        customer_name=res.customer_name,
        items=res.items,
        dataset_path=str(test_jsonl),
    )

    assert os.path.exists(str(test_jsonl))
    with open(str(test_jsonl), "r", encoding="utf-8") as f:
        lines = f.readlines()

    assert len(lines) >= 1
    record = json.loads(lines[0])
    assert record["text"] == msg
    assert record["intent"] == "create_draft"
    assert record["confidence"] >= 0.75
    assert record["customer_name"] == "Sokha"
    assert record["language"] == "mixed"


def test_fine_tuned_neural_classification():
    """Verify inference through the fine-tuned XLM-RoBERTa intent classifier."""
    neural_res = HybridNLPExtractor.classify_intent_neural("invoice Sokha 2 monitors at $450 each")
    assert neural_res is not None
    intent, score = neural_res
    assert intent == IntentEnum.CREATE_DRAFT
    assert score >= 0.70

    # Test Khmer phrasing inference
    khmer_update = HybridNLPExtractor.classify_intent("កែប្រែចំនួន monitor ជា 3 គ្រឿង")
    assert khmer_update[0] == IntentEnum.UPDATE_DRAFT
    assert khmer_update[1] >= 0.70

