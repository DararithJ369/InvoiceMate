import datetime
import json
import logging
import os
import re
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from invoicemate.core.config import settings
from invoicemate.models.enums import IntentEnum
from invoicemate.schemas.llm_extraction import ExtractionPayload, ExtractedItem
from invoicemate.services.khmer_normalizer import clean_khmer_text, segment_khmer_text

logger = logging.getLogger(__name__)

# Zero-shot intent definitions & candidate descriptions
INTENT_CANDIDATES = {
    IntentEnum.CREATE_DRAFT: [
        "create invoice", "bill customer", "new invoice", "send bill",
        "ធ្វើ invoice", "គិតលុយ", "ចេញវិក្កយបត្រ", "ធ្វើវិក្កយបត្រ",
    ],
    IntentEnum.UPDATE_DRAFT: [
        "update invoice", "actually make it", "change to", "add item", "modify bill",
        "កែប្រែ", "ប្តូរជា", "បន្ថែម", "កែជា",
    ],
    IntentEnum.CONFIRM: [
        "confirm", "looks good", "send it", "approved", "yes", "correct",
        "យល់ព្រម", "ផ្ញើទៅ", "ត្រឹមត្រូវ", "យល់ព្រមផ្ញើ",
    ],
    IntentEnum.CANCEL: [
        "cancel", "nevermind", "discard", "delete draft", "stop",
        "បោះបង់", "លុបចោល", "ឈប់",
    ],
    IntentEnum.SEARCH: [
        "search invoice", "find invoice", "show invoices", "list invoices", "history",
        "ស្វែងរក", "រកមើលវិក្កយបត្រ", "បង្ហាញវិក្កយបត្រ",
    ],
    IntentEnum.SELECT_CUSTOMER: [
        "select customer", "choose customer", "pick customer",
        "ជ្រើសរើស", "រើសអតិថិជន",
    ],
    IntentEnum.CLARIFY_NEEDED: [
        "unclear request", "incomplete bill", "missing information",
    ],
}

LABEL_TO_INTENT = {
    "create_draft": IntentEnum.CREATE_DRAFT,
    "update_draft": IntentEnum.UPDATE_DRAFT,
    "confirm": IntentEnum.CONFIRM,
    "cancel": IntentEnum.CANCEL,
    "search": IntentEnum.SEARCH,
    "select_customer": IntentEnum.SELECT_CUSTOMER,
    "clarify_needed": IntentEnum.CLARIFY_NEEDED,
    "greeting": IntentEnum.GREETING,
    "thanks": IntentEnum.THANKS,
    "help": IntentEnum.HELP,
}


def detect_language(text: str) -> str:
    """Detect whether text is Khmer ('km'), English ('en'), or code-switched ('mixed')."""
    has_khmer = bool(re.search(r"[\u1780-\u17FF]", text))
    has_latin = bool(re.search(r"[a-zA-Z]", text))
    if has_khmer and has_latin:
        return "mixed"
    elif has_khmer:
        return "km"
    return "en"


def log_interaction_to_dataset(
    text: str,
    intent: IntentEnum,
    confidence: float,
    customer_name: Optional[str] = None,
    items: Optional[List[ExtractedItem]] = None,
    language: Optional[str] = None,
    dataset_path: Optional[str] = None,
) -> None:
    """
    Log user interaction and parsed attributes directly into JSONL dataset for Track B fine-tuning.
    """
    target_path = dataset_path or settings.INTENT_DATASET_PATH
    os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)

    record = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "text": text,
        "intent": intent.value if isinstance(intent, IntentEnum) else str(intent),
        "confidence": round(float(confidence), 4),
        "customer_name": customer_name,
        "items": [
            {"name": i.name, "qty": float(i.qty), "unit_price": float(i.unit_price)}
            for i in (items or [])
        ],
        "language": language or detect_language(text),
    }

    try:
        with open(target_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning(f"Failed to log interaction to {target_path}: {e}")


class HybridNLPExtractor:
    """
    Option 2 (2-Model Hybrid Setup):
    - Step 0: Preprocessing (khmernormalizer + khmer-nltk word segmentation)
    - Step 1: Model 1 Zero-Shot Intent Classifier
    - Step 2: Model 2 GLiNER Zero-Shot Entity Extractor
    - Step 3: Confidence gating & Pydantic validation
    """

    _gliner_model = None
    _classifier_pipeline = None
    _intent_model = None
    _intent_tokenizer = None

    @classmethod
    def get_intent_classifier(cls):
        """Lazy load fine-tuned XLM-RoBERTa intent classifier if weights exist on disk."""
        if cls._intent_model is None:
            model_path = os.getenv("INTENT_MODEL_PATH", "models/intent_classifier")
            if os.path.exists(model_path) and (
                os.path.exists(os.path.join(model_path, "model.safetensors"))
                or os.path.exists(os.path.join(model_path, "pytorch_model.bin"))
            ):
                try:
                    import torch
                    from transformers import AutoTokenizer, AutoModelForSequenceClassification

                    cls._intent_tokenizer = AutoTokenizer.from_pretrained(model_path)
                    cls._intent_model = AutoModelForSequenceClassification.from_pretrained(model_path)
                    cls._intent_model.eval()
                    logger.info(f"Loaded fine-tuned intent classifier from {model_path}")
                except Exception as e:
                    logger.warning(f"Could not load fine-tuned intent classifier from {model_path}: {e}")
                    cls._intent_model = False
            else:
                cls._intent_model = False
        return (cls._intent_model, cls._intent_tokenizer) if cls._intent_model is not False else (None, None)

    @classmethod
    def classify_intent_neural(cls, text: str) -> Optional[Tuple[IntentEnum, float]]:
        """Run text through fine-tuned XLM-RoBERTa model if loaded."""
        model, tokenizer = cls.get_intent_classifier()
        if not model or not tokenizer:
            return None
        try:
            import torch
            segmented = segment_khmer_text(text)
            inputs = tokenizer(segmented, return_tensors="pt", truncation=True, max_length=128)
            with torch.no_grad():
                logits = model(**inputs).logits
                probs = torch.softmax(logits, dim=-1)[0]
                top_idx = torch.argmax(probs).item()
                confidence = float(probs[top_idx].item())
                label = model.config.id2label.get(top_idx)
                if label and label in LABEL_TO_INTENT:
                    return LABEL_TO_INTENT[label], round(confidence, 2)
        except Exception as e:
            logger.warning(f"Neural intent classification error: {e}")
        return None

    @classmethod
    def get_gliner(cls):
        """Lazy load GLiNER model to prevent unnecessary overhead if offline or unconfigured."""
        if cls._gliner_model is None:
            if os.getenv("ENABLE_GLINER", "0") != "1":
                cls._gliner_model = False
                return None
            try:
                from gliner import GLiNER
                model_name = getattr(settings, "GLINER_MODEL_NAME", "urchade/gliner_multi-v2.1")
                cls._gliner_model = GLiNER.from_pretrained(model_name)
            except Exception as e:
                logger.warning(f"GLiNER model could not be loaded ({e}). Using heuristic entity extraction fallback.")
                cls._gliner_model = False
        return cls._gliner_model if cls._gliner_model is not False else None

    @classmethod
    def classify_intent(cls, text: str, current_draft: Optional[Dict[str, Any]] = None) -> Tuple[IntentEnum, float]:
        """
        Model 1: Intent Classification with confidence score.
        Combines deterministic regex guards, draft context, and fine-tuned XLM-RoBERTa neural inference.
        """
        cleaned = text.strip().lower()

        # 1. Greeting indicators (English + Khmer)
        if re.search(r"^(?:hi|hello|hey|good\s+morning|good\s+afternoon|good\s+evening|greetings|howdy|សួស្ដី|សួស្តី|ជំរាបសួរ|ជំរាបសួរលោក|ជំរាបសួរអ្នក|សុខសប្បាយ|អរុណសួស្ដី)[!.\s]*$", cleaned, re.IGNORECASE):
            return IntentEnum.GREETING, 0.99

        # 2. Thanks indicators (English + Khmer)
        if re.search(r"^(?:thank\s+you|thanks|thx|thank\s+u|many\s+thanks|អរគុណ|សូមអរគុណ|អរគុណច្រើន)[!.\s]*$", cleaned, re.IGNORECASE):
            return IntentEnum.THANKS, 0.99

        # 3. Help indicators (English + Khmer)
        if re.search(r"^(?:help|what\s+can\s+you\s+do|commands|how\s+to\s+use|តើ\s*អ្នក\s*អាច\s*ធ្វើ\s*អ្វី\s*បាន|ជួយ|របៀប\s*ប្រើ)[?!\s]*$", cleaned, re.IGNORECASE):
            return IntentEnum.HELP, 0.99

        # 4. Confirm indicators
        if re.search(r"^(?:confirm|confirm\s+invoice|looks\s+good|send\s+it|yes|ok|correct|approved|proceed|យល់ព្រម|ផ្ញើទៅ|ត្រឹមត្រូវ|បាទ|ចាស)[!.\s]*$", cleaned, re.IGNORECASE):
            return IntentEnum.CONFIRM, 0.98

        # 5. Cancel entire draft indicators
        if re.search(r"^(?:cancel|cancel\s+invoice|cancel\s+draft|nevermind|discard|delete\s+draft|clear|/clear|stop|abort|បោះបង់|លុបចោល|ឈប់)[!.\s]*$", cleaned, re.IGNORECASE):
            return IntentEnum.CANCEL, 0.98

        # 6. Update draft indicators when draft is currently open
        if current_draft:
            # 6a. Item removal or cancellation from draft (e.g. cancel desktop case, remove monitors)
            if re.search(r"\b(?:cancel|remove|delete|drop|cut|take\s+off|no|without|លុប|កាត់ចោល|ដកចេញ|បោះបង់)\s+(?:item\s+|the\s+)?([A-Za-z0-9\u1780-\u17FF\s]+)", cleaned):
                return IntentEnum.UPDATE_DRAFT, 0.98

            # 6b. General update keywords
            if re.search(r"\b(?:actually|change|make|update|set|add|remove|delete|drop|cancel|instead|with|quantity|qty|price|កែ|ប្តូរ|ថែម|លុប|ដូរ)\b", cleaned):
                return IntentEnum.UPDATE_DRAFT, 0.95

            # 6c. Item name mentioned in text while draft is open
            items_list = current_draft.get("items", [])
            for itm in items_list:
                itm_name = (itm.get("product_name") or itm.get("name") or "").lower()
                if itm_name and (itm_name in cleaned or any(len(w) > 3 and w in cleaned for w in itm_name.split())):
                    return IntentEnum.UPDATE_DRAFT, 0.95

        # 7. Search indicators
        if re.search(r"^(?:find|search|show\s+(?:my\s+)?invoices?|list\s+invoices?|ស្វែងរក|រកមើល)", cleaned, re.IGNORECASE):
            return IntentEnum.SEARCH, 0.92

        # 8. Select customer
        if re.search(r"^(?:choose|select|customer)\s+\d+|^\d+$", cleaned, re.IGNORECASE):
            if current_draft and "customer_name" not in current_draft:
                return IntentEnum.SELECT_CUSTOMER, 0.90

        # 9. Create draft indicators (e.g. invoice sokha, bill dara, គិតលុយ, ធ្វើ invoice)
        if re.search(r"(?:invoice|bill|create\s+invoice|គិតលុយ|ធ្វើ\s*invoice|វិក្កយបត្រ)\s+([A-Za-z0-9\u1780-\u17FF]+)", cleaned, re.IGNORECASE):
            # Check if items/price mentioned
            if re.search(r"\$|\b\d+\s*(?:usd|khr|riel|រៀល|៛)|(?:at|for|@|ថ្លៃ)\s*\$?\d+", cleaned):
                return IntentEnum.CREATE_DRAFT, 0.94
            else:
                return IntentEnum.CLARIFY_NEEDED, 0.85

        # 10. Fine-tuned Neural Classification (XLM-RoBERTa)
        neural_res = cls.classify_intent_neural(text)
        if neural_res and neural_res[1] >= 0.70:
            return neural_res

        # 11. Heuristic fallback: customer + items + price but lacks prefix
        if re.search(r"(\$|\b\d+\s*(?:usd|khr|riel|រៀល|៛))", cleaned) and re.search(r"[A-Za-z\u1780-\u17FF]{2,}", cleaned):
            return IntentEnum.CREATE_DRAFT, 0.82

        return IntentEnum.CLARIFY_NEEDED, 0.50

    @classmethod
    def extract_entities_gliner(
        cls, processed_text: str, intent: IntentEnum, current_draft: Optional[Dict[str, Any]] = None
    ) -> Tuple[Optional[str], List[ExtractedItem], Optional[str], Optional[str]]:
        """
        Model 2: Extract entities via GLiNER zero-shot entity matching with deterministic fallback.
        """
        gliner = cls.get_gliner()
        customer_name = None
        extracted_items: List[ExtractedItem] = []
        currency = "USD"
        due_date = None

        if intent == IntentEnum.UPDATE_DRAFT and current_draft:
            from invoicemate.services.llm_extractor import RuleBasedFallbackExtractor
            fb = RuleBasedFallbackExtractor.extract(processed_text, current_draft=current_draft)
            return (fb.customer_name, fb.items, fb.currency or currency, fb.due_date)

        if gliner:
            try:
                labels = ["BUYER_NAME", "PRODUCT_NAME", "PRICE", "QUANTITY", "CURRENCY", "DUE_DATE"]
                entities = gliner.predict_entities(processed_text, labels, threshold=0.45)

                current_item_name = None
                current_price = None
                current_qty = 1.0

                for ent in entities:
                    lbl = ent["label"]
                    txt = ent["text"].strip()

                    if lbl == "BUYER_NAME" and not customer_name:
                        customer_name = txt
                    elif lbl == "CURRENCY":
                        if re.search(r"(?:khr|riel|រៀល|៛)", txt, re.IGNORECASE):
                            currency = "KHR"
                        else:
                            currency = "USD"
                    elif lbl == "DUE_DATE":
                        due_date = txt
                    elif lbl == "PRODUCT_NAME":
                        current_item_name = txt
                    elif lbl == "PRICE":
                        p_match = re.search(r"(\d+(?:\.\d+)?)", txt)
                        if p_match:
                            current_price = float(p_match.group(1))
                    elif lbl == "QUANTITY":
                        q_match = re.search(r"(\d+(?:\.\d+)?)", txt)
                        if q_match:
                            current_qty = float(q_match.group(1))

                if current_item_name:
                    extracted_items.append(
                        ExtractedItem(
                            name=current_item_name,
                            qty=Decimal(str(current_qty)),
                            unit_price=Decimal(str(current_price or 0.0)),
                        )
                    )
            except Exception as e:
                logger.warning(f"GLiNER entity extraction failed: {e}")

        # If GLiNER didn't extract items or wasn't available, apply deterministic extraction
        if not extracted_items:
            from invoicemate.services.llm_extractor import RuleBasedFallbackExtractor
            fb = RuleBasedFallbackExtractor.extract(processed_text, current_draft=current_draft)
            customer_name = customer_name or fb.customer_name
            extracted_items = fb.items
            currency = fb.currency or currency
            due_date = fb.due_date or due_date

        return customer_name, extracted_items, currency, due_date

    @classmethod
    def extract(cls, raw_message: str, current_draft: Optional[Dict[str, Any]] = None) -> ExtractionPayload:
        """
        Execute Option 2 (2-Model Hybrid Setup):
        1. Preprocess & Segment text
        2. Classify intent (Model 1)
        3. Extract entities (Model 2)
        4. Validate confidence and Pydantic schema
        5. Log interaction to JSONL dataset
        """
        # Step 0: Preprocessing (Khmer cleaning + word segmentation)
        preprocessed_text = segment_khmer_text(raw_message)
        lang = detect_language(raw_message)

        # Step 1: Model 1 Inference — Intent Classification
        intent, confidence = cls.classify_intent(preprocessed_text, current_draft=current_draft)

        # Confidence Gate: Route low confidence to clarify_needed
        if confidence < 0.75:
            res = ExtractionPayload(
                intent=IntentEnum.CLARIFY_NEEDED,
                confidence=confidence,
                clarification_question="I could not understand your request clearly. Please clarify the customer or items for this invoice.",
            )
            log_interaction_to_dataset(raw_message, IntentEnum.CLARIFY_NEEDED, confidence, language=lang)
            return res

        # Step 2: Model 2 Inference — Entity Extraction
        customer_name = None
        extracted_items: List[ExtractedItem] = []
        currency = "USD"
        due_date = None
        search_query = None

        if intent in [IntentEnum.CREATE_DRAFT, IntentEnum.UPDATE_DRAFT]:
            customer_name, extracted_items, currency, due_date = cls.extract_entities_gliner(
                preprocessed_text, intent, current_draft=current_draft
            )
        elif intent == IntentEnum.SEARCH:
            # Extract query term
            m = re.search(r"(?:find|search|ស្វែងរក|រកមើល)\s+(?:for\s+)?(.+)", preprocessed_text, re.IGNORECASE)
            search_query = m.group(1).strip() if m else preprocessed_text.strip()

        # Step 3: Package into validated Pydantic ExtractionPayload
        payload = ExtractionPayload(
            intent=intent,
            confidence=confidence,
            customer_name=customer_name,
            items=extracted_items,
            currency=currency,
            due_date=due_date,
            search_query=search_query,
        )

        # Step 4: Log to dataset for Track B fine-tuning curation
        log_interaction_to_dataset(
            text=raw_message,
            intent=intent,
            confidence=confidence,
            customer_name=customer_name,
            items=extracted_items,
            language=lang,
        )

        return payload


def extract_intent_hybrid(message: str, current_draft: Optional[Dict[str, Any]] = None) -> ExtractionPayload:
    """Functional entrypoint for Option 2 hybrid extraction."""
    return HybridNLPExtractor.extract(message, current_draft=current_draft)
