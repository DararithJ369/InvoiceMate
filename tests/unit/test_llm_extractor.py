from decimal import Decimal
import pytest
from invoicemate.services.llm_extractor import extract_intent


TEST_BENCHMARK_PHRASES = [
    # --- 10 Create Draft phrases ---
    {
        "phrase": "Invoice Sokha 2 monitors at $450 each",
        "draft": None,
        "expected_intent": "create_draft",
        "expected_customer": "Sokha",
        "expected_item_count": 1,
    },
    {
        "phrase": "Bill Dara 10 consulting hours at $75 per hour",
        "draft": None,
        "expected_intent": "create_draft",
        "expected_customer": "Dara",
        "expected_item_count": 1,
    },
    {
        "phrase": "Create invoice for Bopha Coffee 5 bags of coffee beans at $12",
        "draft": None,
        "expected_intent": "create_draft",
        "expected_customer": "Bopha Coffee",
        "expected_item_count": 1,
    },
    {
        "phrase": "Invoice Vandy 1 logistics service at $150",
        "draft": None,
        "expected_intent": "create_draft",
        "expected_customer": "Vandy",
        "expected_item_count": 1,
    },
    {
        "phrase": "Bill Rithy 3 desk lamps at $35 each",
        "draft": None,
        "expected_intent": "create_draft",
        "expected_customer": "Rithy",
        "expected_item_count": 1,
    },
    {
        "phrase": "Invoice Chan 100000 KHR for delivery",
        "draft": None,
        "expected_intent": "create_draft",
        "expected_customer": "Chan",
        "expected_item_count": 1,
    },
    {
        "phrase": "Bill Sophal 4 chairs at $50 each due in 14 days",
        "draft": None,
        "expected_intent": "create_draft",
        "expected_customer": "Sophal",
        "expected_item_count": 1,
    },
    {
        "phrase": "Invoice Piseth $500 for web development",
        "draft": None,
        "expected_intent": "create_draft",
        "expected_customer": "Piseth",
        "expected_item_count": 1,
    },
    {
        "phrase": "Invoice Nary 12 notebooks at $2.50 each",
        "draft": None,
        "expected_intent": "create_draft",
        "expected_customer": "Nary",
        "expected_item_count": 1,
    },
    {
        "phrase": "Bill Maly 1 printing job at $80",
        "draft": None,
        "expected_intent": "create_draft",
        "expected_customer": "Maly",
        "expected_item_count": 1,
    },

    # --- 4 Update Draft phrases ---
    {
        "phrase": "actually make it 4 monitors",
        "draft": {
            "customer_name": "Sokha",
            "items": [{"name": "monitors", "quantity": 2, "unit_price": 450}],
            "currency": "USD",
        },
        "expected_intent": "update_draft",
        "expected_customer": "Sokha",
        "expected_item_count": 1,
    },
    {
        "phrase": "change to 3",
        "draft": {
            "customer_name": "Sokha",
            "items": [{"name": "monitors", "quantity": 2, "unit_price": 450}],
            "currency": "USD",
        },
        "expected_intent": "update_draft",
        "expected_customer": "Sokha",
        "expected_item_count": 1,
    },
    {
        "phrase": "add 1 keyboard for $25",
        "draft": {
            "customer_name": "Sokha",
            "items": [{"name": "monitors", "quantity": 2, "unit_price": 450}],
            "currency": "USD",
        },
        "expected_intent": "update_draft",
        "expected_customer": "Sokha",
        "expected_item_count": 2,
    },
    {
        "phrase": "add 2 mouse pads for $5",
        "draft": {
            "customer_name": "Dara",
            "items": [{"name": "consulting", "quantity": 10, "unit_price": 75}],
            "currency": "USD",
        },
        "expected_intent": "update_draft",
        "expected_customer": "Dara",
        "expected_item_count": 2,
    },

    # --- 5 Confirm phrases ---
    {"phrase": "confirm", "draft": None, "expected_intent": "confirm"},
    {"phrase": "looks good", "draft": None, "expected_intent": "confirm"},
    {"phrase": "send it", "draft": None, "expected_intent": "confirm"},
    {"phrase": "yes", "draft": None, "expected_intent": "confirm"},
    {"phrase": "confirm invoice", "draft": None, "expected_intent": "confirm"},

    # --- 5 Cancel phrases ---
    {"phrase": "cancel", "draft": None, "expected_intent": "cancel"},
    {"phrase": "nevermind", "draft": None, "expected_intent": "cancel"},
    {"phrase": "discard", "draft": None, "expected_intent": "cancel"},
    {"phrase": "cancel invoice", "draft": None, "expected_intent": "cancel"},
    {"phrase": "delete draft", "draft": None, "expected_intent": "cancel"},

    # --- 4 Search phrases ---
    {"phrase": "find Dara invoice", "draft": None, "expected_intent": "search"},
    {"phrase": "show my invoices this week", "draft": None, "expected_intent": "search"},
    {"phrase": "search for Sokha", "draft": None, "expected_intent": "search"},
    {"phrase": "list invoices", "draft": None, "expected_intent": "search"},

    # --- 2 Clarify Needed phrases ---
    {"phrase": "bill someone $50", "draft": None, "expected_intent": "clarify_needed"},
    {"phrase": "invoice Sokha", "draft": None, "expected_intent": "clarify_needed"},
]


def test_llm_extractor_30_phrase_benchmark():
    total_phrases = len(TEST_BENCHMARK_PHRASES)
    assert total_phrases == 30, f"Expected 30 benchmark phrases, got {total_phrases}"

    correct_intents = 0

    for idx, test_case in enumerate(TEST_BENCHMARK_PHRASES, 1):
        phrase = test_case["phrase"]
        draft = test_case["draft"]
        expected_intent = test_case["expected_intent"]

        res = extract_intent(phrase, current_draft=draft)

        if res.intent == expected_intent:
            correct_intents += 1

        assert res.intent == expected_intent, (
            f"Case #{idx} failed for phrase '{phrase}': expected intent '{expected_intent}', got '{res.intent}'"
        )

    accuracy = (correct_intents / total_phrases) * 100
    print(f"\nBenchmark Accuracy: {accuracy:.2f}% ({correct_intents}/{total_phrases})")
    assert accuracy >= 90.0, f"Extraction accuracy target (>=90%) failed: got {accuracy:.2f}%"


def test_compound_and_sequential_item_updates():
    draft = {
        "id": 1,
        "customer_name": "Sokha",
        "currency": "USD",
        "items": [{"product_name": "monitors", "quantity": 2, "unit_price": 450}],
    }

    # Compound message: quantity change + add new item
    res = extract_intent("actually make it 3 monitors and add 1 keyboard for $25", current_draft=draft)
    assert res.intent == "update_draft"
    assert len(res.items) == 2
    assert res.items[0].name == "monitors"
    assert res.items[0].qty == Decimal("3.0")
    assert res.items[1].name == "keyboard"
    assert res.items[1].qty == Decimal("1.0")
    assert res.items[1].unit_price == Decimal("25.0")


def test_extract_intent_empty_items_clarify_needed():
    from invoicemate.schemas.llm_extraction import LLMExtractionResult
    from invoicemate.services.llm_extractor import _normalize_extraction_result

    # Mock an extraction that returned create_draft without items
    raw_res = LLMExtractionResult(intent="create_draft", customer_name="Sokha", items=[])
    norm_res = _normalize_extraction_result(raw_res)
    assert norm_res.intent == "clarify_needed"
    assert "Sokha" in norm_res.clarification_question


def test_cancel_and_remove_draft_items():
    draft = {
        "id": 1,
        "customer_name": "Sokha",
        "currency": "USD",
        "items": [
            {"product_name": "monitors", "quantity": 2, "unit_price": 450},
            {"product_name": "desktop case", "quantity": 1, "unit_price": 120},
        ],
    }

    # 1. cancel item by name
    res = extract_intent("cancel desktop case", current_draft=draft)
    assert res.intent == "update_draft"
    assert len(res.items) == 1
    assert res.items[0].name == "monitors"

    # 2. remove item by name
    res2 = extract_intent("remove monitors", current_draft=draft)
    assert res2.intent == "update_draft"
    assert len(res2.items) == 1
    assert res2.items[0].name == "desktop case"

    # 3. cancel whole draft
    res3 = extract_intent("cancel draft", current_draft=draft)
    assert res3.intent == "cancel"


def test_update_draft_price_and_quantity():
    draft = {
        "id": 1,
        "customer_name": "Naroth",
        "currency": "USD",
        "items": [
            {"product_name": "iPhone 17 Pro Max 1TB", "quantity": 2, "unit_price": 1250},
            {"product_name": "Macbook Pro M1 32GB 1TB", "quantity": 2, "unit_price": 1200},
        ],
    }

    # 1. Update only unit price
    res1 = extract_intent("actually make Macbook Pro M1 at 1150$ for each", current_draft=draft)
    assert res1.intent == "update_draft"
    assert len(res1.items) == 2
    assert res1.items[0].unit_price == Decimal("1250.0")
    assert res1.items[0].qty == Decimal("2.0")
    assert res1.items[1].name == "Macbook Pro M1 32GB 1TB"
    assert res1.items[1].unit_price == Decimal("1150.0")
    assert res1.items[1].qty == Decimal("2.0")

    # 2. Update both quantity and unit price
    res2 = extract_intent("actually make 3 Macbook Pro M1 for 1100$ for each", current_draft=draft)
    assert res2.intent == "update_draft"
    assert res2.items[1].unit_price == Decimal("1100.0")
    assert res2.items[1].qty == Decimal("3.0")



