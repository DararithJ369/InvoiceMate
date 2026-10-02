import json
import os
import re
from decimal import Decimal
from typing import Optional, Dict, Any, List

from invoicemate.core.config import settings
from invoicemate.models.enums import IntentEnum
from invoicemate.schemas.llm_extraction import ExtractionPayload, ExtractedItem, LLMExtractionResult
from invoicemate.services.khmer_normalizer import clean_khmer_text

CONFIDENCE_THRESHOLD = 0.75

SYSTEM_PROMPT = """You are an intent extraction engine for InvoiceAI, a chat-native invoicing platform for Cambodian SMEs and freelancers.
Your sole job is to extract structured entities from natural language messages (in English, Khmer, or mixed Khmer-English).

## Output Contract
You must output ONLY a valid JSON object strictly conforming to this schema without any preamble, markdown fences, or conversational text:

{
  "intent": "create_draft" | "update_draft" | "confirm" | "cancel" | "search" | "select_customer" | "clarify_needed",
  "confidence": 0.0 to 1.0,
  "customer_name": string or null,
  "items": [
    {"name": string, "qty": number, "unit_price": number}
  ],
  "due_date": string or null,
  "currency": string or null,
  "search_query": string or null,
  "clarification_question": string or null
}

## Intent Rules
1. create_draft: Used when user wants to create an invoice with items and prices.
2. update_draft: Used when updating an active draft.
3. confirm: User approves current draft.
4. cancel: User discards current draft.
5. search: User searches invoice history.
6. clarify_needed: Missing customer or items.
"""

WORD_TO_NUM = {
    "a": 1.0,
    "an": 1.0,
    "one": 1.0,
    "two": 2.0,
    "three": 3.0,
    "four": 4.0,
    "five": 5.0,
    "six": 6.0,
    "seven": 7.0,
    "eight": 8.0,
    "nine": 9.0,
    "ten": 10.0,
    "eleven": 11.0,
    "twelve": 12.0,
    "dozen": 12.0,
    "twenty": 20.0,
    "thirty": 30.0,
    "forty": 40.0,
    "fifty": 50.0,
    "hundred": 100.0,
}


def _clean_item_text(text: str, customer_name: Optional[str] = None) -> str:
    cleaned = text.strip()
    cleaned = re.sub(
        r"^(?:i\s+want\s+to\s+)?(?:create\s+(?:an\s+)?invoice\s+(?:for\s+)?|បង្កើត\s*(?:វិក្កយបត្រ|invoice)?\s*(?:សម្រាប់|ឱ្យ|ជូន)?|bill|invoice|វិក្កយបត្រ|គិតលុយ)\s*(?:[A-Za-z0-9\u1780-\u17FF\s]+?[:\n,]|\s+)?",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    if customer_name and customer_name.lower() in cleaned.lower():
        cleaned = re.sub(re.escape(customer_name), "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned.strip(" ,;:-")


def _parse_segment_item(seg: str, customer_name: Optional[str] = None) -> Optional[ExtractedItem]:
    cleaned = seg.lstrip("-*• \t").strip()
    if not cleaned:
        return None

    cleaned = _clean_item_text(cleaned, customer_name)
    cleaned = cleaned.lstrip("-*• \t").strip()
    if not cleaned:
        return None

    price = None
    qty = 1.0
    item_part = None

    # 1. Preposition + price: at $450, for $25, @ 10, for 100000 KHR, ថ្លៃ 50$
    m = re.search(
        r"(?:at|for|@|is|costs?|cost|price|ថ្លៃ|តម្លៃ|:)\s*(\$|usd|khr|riel|រៀល|៛)?\s*(\d+(?:\.\d+)?)\s*(\$|usd|khr|riel|រៀល|៛|dollars?|bucks?)?(?:\s*(?:each|per\s+\w+|pcs|units?))?",
        cleaned,
        re.IGNORECASE,
    )
    if m and m.group(2):
        price = float(m.group(2))
        before = cleaned[:m.start()].strip().rstrip(",;:- ")
        after = cleaned[m.end():].strip().lstrip(",;:- ")
        after = re.sub(r"^(?:for|of|ថ្លៃ)\s+", "", after, flags=re.IGNORECASE).strip()
        item_part = before if before else after
    else:
        # 2. Currency symbol before/after number
        m2 = re.search(
            r"(\$|usd|khr|riel|រៀល|៛)\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(\$|usd|khr|riel|រៀល|៛|dollars?|bucks?)",
            cleaned,
            re.IGNORECASE,
        )
        if m2:
            price = float(m2.group(2)) if m2.group(2) else float(m2.group(3))
            before = cleaned[:m2.start()].strip().rstrip(",;:- ")
            after = cleaned[m2.end():].strip().lstrip(",;:- ")
            after = re.sub(r"^(?:each|per\s+\w+|pcs|units?)\b", "", after, flags=re.IGNORECASE).strip()
            after = re.sub(r"^(?:for|of)\s+", "", after, flags=re.IGNORECASE).strip()
            item_part = before if before else after

    if price is None or not item_part:
        return None

    item_part = _clean_item_text(item_part, customer_name)

    # Extract quantity
    qty_m = re.match(r"^(\d+(?:\.\d+)?)\s+(.*)$", item_part)
    if qty_m:
        qty = float(qty_m.group(1))
        item_name = qty_m.group(2).strip()
    else:
        words = item_part.split()
        if words and words[0].lower() in WORD_TO_NUM:
            qty = WORD_TO_NUM[words[0].lower()]
            item_name = " ".join(words[1:]).strip()
        else:
            qty = 1.0
            item_name = item_part

    item_name = re.sub(r"\b(each|per\s+hour|hr|pcs|units?)\b", "", item_name, flags=re.IGNORECASE).strip()
    item_name = item_name.strip(" ,;:-")
    if not item_name:
        item_name = "Item"

    return ExtractedItem(name=item_name, qty=qty, unit_price=price)


class RuleBasedFallbackExtractor:
    """
    Deterministic rule-based intent extractor for offline testing & benchmark execution.
    Handles bilingual Khmer and English commands with high confidence.
    """

    @staticmethod
    def extract(message: str, current_draft: Optional[Dict[str, Any]] = None) -> ExtractionPayload:
        msg = clean_khmer_text(message)
        lower_msg = msg.lower()

        # 0. Check Greeting, Thanks, and Help Intents
        greeting_words = ["hi", "hello", "hey", "good morning", "good afternoon", "good evening", "greetings", "howdy", "សួស្ដី", "សួស្តី", "ជំរាបសួរ", "សុខសប្បាយ", "អរុណសួស្ដី"]
        if lower_msg in greeting_words or any(lower_msg == w for w in greeting_words):
            return ExtractionPayload(intent=IntentEnum.GREETING, confidence=0.99)

        thanks_words = ["thank you", "thanks", "thx", "thank u", "many thanks", "អរគុណ", "សូមអរគុណ", "អរគុណច្រើន"]
        if lower_msg in thanks_words or any(lower_msg == w for w in thanks_words):
            return ExtractionPayload(intent=IntentEnum.THANKS, confidence=0.99)

        help_words = ["help", "what can you do", "commands", "how to use", "តើអ្នកអាចធ្វើអ្វីបាន", "តើ អ្នក អាច ធ្វើ អ្វី បាន", "ជួយ", "របៀបប្រើ", "របៀប ប្រើ"]
        if lower_msg in help_words or any(lower_msg == w for w in help_words):
            return ExtractionPayload(intent=IntentEnum.HELP, confidence=0.99)

        # 1. Check Confirm Intent (English + Khmer)
        confirm_words = ["confirm", "send it", "looks good", "yes", "approved", "confirm invoice", "proceed", "យល់ព្រម", "ផ្ញើទៅ", "ត្រឹមត្រូវ"]
        if lower_msg in confirm_words or any(lower_msg == w for w in confirm_words):
            return ExtractionPayload(intent=IntentEnum.CONFIRM, confidence=0.98)

        # 2. Check Cancel / Clear Intent (English + Khmer)
        cancel_words = ["cancel", "nevermind", "discard", "cancel invoice", "delete draft", "clear", "/clear", "បោះបង់", "លុបចោល", "ឈប់"]
        if lower_msg in cancel_words or any(lower_msg == w for w in cancel_words):
            return ExtractionPayload(intent=IntentEnum.CANCEL, confidence=0.98)

        # 3. Check Search Intent (English + Khmer)
        search_triggers = ["find", "search", "show my", "list", "lookup", "ស្វែងរក", "រកមើល"]
        if any(lower_msg.startswith(t) for t in search_triggers) or ("invoices" in lower_msg and "create" not in lower_msg):
            query = msg
            for prefix in ["find invoice for", "find invoices for", "find", "search for", "show my invoices for", "show my", "list", "ស្វែងរក", "រកមើល"]:
                if lower_msg.startswith(prefix):
                    query = msg[len(prefix):].strip()
                    break
            return ExtractionPayload(intent=IntentEnum.SEARCH, confidence=0.95, search_query=query or msg)

        # 4. Check Update Draft Intent
        is_update_keyword = any(kw in lower_msg for kw in [
            "actually", "change", "add ", "add", "remove", "delete", "cancel", "drop",
            "take off", "cut", "no ", "without", "make it", "make ", "instead of",
            "with ", "កែប្រែ", "ប្តូរ", "ថែម", "លុប", "កាត់ចោល", "ដកចេញ", "កែ"
        ])
        if (current_draft and current_draft.get("items") and is_update_keyword):
            existing_items_map = []
            for itm in current_draft["items"]:
                name = itm.get("product_name") or itm.get("name", "Item")
                qty = float(itm.get("quantity") or itm.get("qty", 1))
                price = float(itm.get("unit_price") or itm.get("price", 0))
                existing_items_map.append({"name": name, "qty": qty, "price": price})

            # 4a. Check for item removal (by name, keyword, or index)
            remove_match = re.search(
                r"(?:remove|delete|cancel|drop|take\s+off|cut|លុប|កាត់ចោល|ដកចេញ|បោះបង់)\s+(?:item\s+|the\s+)?(.+)",
                lower_msg,
                re.IGNORECASE,
            )
            if remove_match:
                rem_target = remove_match.group(1).strip().rstrip(" .,!?;:")
                # Check if target is an index like "item 2", "2", "#2"
                idx_match = re.search(r"^(?:#|item\s+|no\.?\s*)?(\d+)(?:st|nd|rd|th)?$", rem_target, re.IGNORECASE)
                if idx_match:
                    target_num = int(idx_match.group(1))
                    if 1 <= target_num <= len(existing_items_map):
                        existing_items_map.pop(target_num - 1)
                else:
                    clean_target = re.sub(r"^(?:the|an?|one|\d+)\s+", "", rem_target, flags=re.IGNORECASE).strip()
                    target_words = set(re.findall(r"[a-zA-Z0-9\u1780-\u17FF]+", clean_target.lower()))

                    new_items = []
                    removed_any = False
                    for itm in existing_items_map:
                        name_l = itm["name"].lower()
                        item_words = set(re.findall(r"[a-zA-Z0-9\u1780-\u17FF]+", name_l))

                        is_match = False
                        if rem_target.lower() in name_l or name_l in rem_target.lower():
                            is_match = True
                        elif clean_target and (clean_target in name_l or name_l in clean_target):
                            is_match = True
                        elif target_words and (target_words.issubset(item_words) or item_words.issubset(target_words)):
                            is_match = True
                        elif target_words and len(target_words.intersection(item_words)) >= 1:
                            common = target_words.intersection(item_words)
                            if any(len(w) > 2 for w in common):
                                is_match = True

                        if is_match and not removed_any:
                            removed_any = True
                            continue
                        new_items.append(itm)

                    if removed_any:
                        existing_items_map = new_items

            # 4b. Identify target item for modification by name overlap
            target_idx = None
            best_score = 0
            for idx, itm in enumerate(existing_items_map):
                name_lower = itm["name"].lower()
                if name_lower in lower_msg:
                    score = len(name_lower)
                    if score > best_score:
                        best_score = score
                        target_idx = idx
                else:
                    name_words = [w for w in re.findall(r"[a-zA-Z0-9\u1780-\u17FF]+", name_lower) if len(w) > 2]
                    overlap = sum(1 for w in name_words if w in lower_msg)
                    if overlap > best_score:
                        best_score = overlap
                        target_idx = idx

            # 4c. Extract new quantity
            new_qty = None
            m_prep = re.search(r"(?:with|to|be|as|ជា|ទៅ)\s+(\d+(?:\.\d+)?)", lower_msg)
            if m_prep:
                new_qty = float(m_prep.group(1))
            else:
                m_qty = re.search(r"(?:make\s+it|actually\s+make\s+it|make|change\s+to|change|quantity\s+to|ប្តូរជា|កែជា)\s+(\d+(?:\.\d+)?)", lower_msg)
                if m_qty:
                    new_qty = float(m_qty.group(1))

            if new_qty is not None and existing_items_map:
                if target_idx is None:
                    if len(existing_items_map) == 1:
                        target_idx = 0
                    else:
                        # Prefer item whose current quantity != new_qty
                        candidates = [i for i, itm in enumerate(existing_items_map) if itm["qty"] != new_qty]
                        target_idx = candidates[-1] if candidates else len(existing_items_map) - 1

                if target_idx is not None and 0 <= target_idx < len(existing_items_map):
                    existing_items_map[target_idx]["qty"] = new_qty

            # 4d. Check for adding items
            add_match = re.search(
                r"(?:add|plus|ថែម)\s+(.+?)\s+(?:for|at|\@|ថ្លៃ|តម្លៃ)\s*(\$|usd|៛|riel)?\s*(\d+(?:\.\d+)?)\s*(\$|usd|៛|riel)?",
                lower_msg,
                re.IGNORECASE,
            )
            if add_match:
                raw_item_part = add_match.group(1).strip()
                add_price = float(add_match.group(3))

                add_qty = 1.0
                add_name = raw_item_part

                m_lead = re.match(r"^(\d+(?:\.\d+)?|[a-zA-Z]+)\s+(.+)$", raw_item_part)
                if m_lead:
                    token = m_lead.group(1).lower()
                    rest = m_lead.group(2).strip()
                    if token.replace(".", "", 1).isdigit():
                        add_qty = float(token)
                        add_name = rest
                    elif token in WORD_TO_NUM:
                        add_qty = WORD_TO_NUM[token]
                        add_name = rest

                add_name = re.sub(r"^(?:the|an?)\s+", "", add_name, flags=re.IGNORECASE).strip()

                existing_item_found = False
                for item in existing_items_map:
                    if item["name"].lower() == add_name.lower():
                        item["qty"] += add_qty
                        existing_item_found = True
                        break
                if not existing_item_found:
                    existing_items_map.append({"name": add_name, "qty": add_qty, "price": add_price})

            result_items = [
                ExtractedItem(name=itm["name"], qty=itm["qty"], unit_price=itm["price"])
                for itm in existing_items_map
            ]
            return ExtractionPayload(
                intent=IntentEnum.UPDATE_DRAFT,
                confidence=0.95,
                customer_name=current_draft.get("customer_name"),
                items=result_items,
                currency=current_draft.get("currency", "USD"),
            )

        # 5. Check Create Draft vs Clarify Needed
        currency = "USD"
        if "khr" in lower_msg or "riel" in lower_msg or "រៀល" in lower_msg or "៛" in lower_msg:
            currency = "KHR"
        elif "$" in lower_msg or "usd" in lower_msg:
            currency = "USD"

        # Customer extraction (English & Khmer)
        customer_name = None
        cust_match = re.search(
            r"(?:create\s+(?:an\s+)?invoice\s+(?:for\s+)?|បង្កើត\s*(?:វិក្កយបត្រ|invoice)?\s*(?:សម្រាប់|ឱ្យ|ជូន)?|bill|invoice|គិតលុយ|វិក្កយបត្រ)\s*([A-Za-z0-9\u1780-\u17FF\s]+?)(?::|\n|,|\s+with|\s+\d|$)",
            msg,
            re.IGNORECASE,
        )
        if cust_match:
            candidate = cust_match.group(1).strip()
            candidate = re.sub(r"^(?:for|an|invoice|a|i\s+want\s+to\s+create|ឱ្យ|ជូន|សម្រាប់|បង្កើត)\s*", "", candidate, flags=re.IGNORECASE).strip()
            if candidate.lower() not in ["someone", "somebody", "anyone", "anybody"]:
                customer_name = candidate
        elif current_draft and current_draft.get("customer_name"):
            customer_name = current_draft.get("customer_name")
        else:
            for word in msg.split():
                if word and word[0].isupper() and word.lower() not in ["invoice", "bill", "create", "usd", "khr", "item", "service", "due"]:
                    customer_name = word
                    break

        # Items extraction
        items = []
        segments = re.split(r"[,;\n]+", msg)
        for seg in segments:
            extracted = _parse_segment_item(seg, customer_name=customer_name)
            if extracted:
                items.append(extracted)

        due_date = None
        due_match = re.search(r"due\s+([a-zA-Z0-9\s]+)", lower_msg)
        if due_match:
            due_date = due_match.group(1).strip()

        if not customer_name and not items:
            return ExtractionPayload(
                intent=IntentEnum.CLARIFY_NEEDED,
                confidence=0.90,
                clarification_question="Which customer and items would you like to create an invoice for?",
            )
        elif not items:
            return ExtractionPayload(
                intent=IntentEnum.CLARIFY_NEEDED,
                confidence=0.90,
                customer_name=customer_name,
                clarification_question=f"What items and prices should be on the invoice for {customer_name}?",
            )
        elif not customer_name:
            return ExtractionPayload(
                intent=IntentEnum.CLARIFY_NEEDED,
                confidence=0.90,
                items=items,
                clarification_question="Who is the customer for this invoice?",
            )

        return ExtractionPayload(
            intent=IntentEnum.CREATE_DRAFT,
            confidence=0.95,
            customer_name=customer_name,
            items=items,
            currency=currency,
            due_date=due_date,
        )


def _call_claude_api(user_prompt: str) -> Optional[ExtractionPayload]:
    """Call Anthropic Claude API with temperature 0.0."""
    anthropic_key = settings.ANTHROPIC_API_KEY
    if not anthropic_key or anthropic_key == "your_claude_api_key_here":
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=anthropic_key)
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1000,
            temperature=0.0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        text_content = response.content[0].text.strip()
        if text_content.startswith("```"):
            text_content = re.sub(r"^```(?:json)?\n?", "", text_content)
            text_content = re.sub(r"\n?```$", "", text_content)

        payload = json.loads(text_content)
        return ExtractionPayload(**payload)
    except Exception as err:
        return None


def _call_gemini_api(user_prompt: str) -> Optional[ExtractionPayload]:
    """Call Google Gemini API with temperature 0.0."""
    gemini_key = settings.GEMINI_API_KEY
    if not gemini_key or gemini_key == "your_gemini_api_key_here":
        return None

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=gemini_key)
    for model_name in ["gemini-2.5-flash", "gemini-1.5-flash"]:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    temperature=0.0,
                ),
            )
            text_content = response.text.strip()
            if text_content.startswith("```"):
                text_content = re.sub(r"^```(?:json)?\n?", "", text_content)
                text_content = re.sub(r"\n?```$", "", text_content)

            payload = json.loads(text_content)
            return ExtractionPayload(**payload)
        except Exception:
            continue

    return None


def _normalize_extraction_result(res: ExtractionPayload) -> ExtractionPayload:
    """Ensure extraction payload conforms to domain rules and invariants."""
    valid_items = []
    for itm in res.items:
        if itm.name and str(itm.name).strip() and itm.qty > 0 and itm.unit_price >= 0:
            valid_items.append(itm)
    res.items = valid_items

    if res.intent == IntentEnum.CREATE_DRAFT:
        if not res.items:
            res.intent = IntentEnum.CLARIFY_NEEDED
            if not res.clarification_question:
                if res.customer_name:
                    res.clarification_question = (
                        f"What items, quantities, and prices would you like to invoice for {res.customer_name}?"
                    )
                else:
                    res.clarification_question = (
                        "What items, quantities, and prices would you like to add to this invoice?"
                    )
        elif not res.customer_name:
            res.intent = IntentEnum.CLARIFY_NEEDED
            if not res.clarification_question:
                res.clarification_question = "Who is the customer for this invoice?"

    return res


def extract_intent(
    message: str, current_draft: Optional[Dict[str, Any]] = None, provider: Optional[str] = None
) -> ExtractionPayload:
    """
    Extract intent and structured entities from user natural language input.
    Enforces low-resource Khmer orthographic cleaning, Pydantic schema validation,
    and strict confidence gating (>= 0.75).
    """
    cleaned_message = clean_khmer_text(message)
    chosen_provider = (provider or settings.LLM_PROVIDER).lower()

    user_prompt = f"User message: \"{cleaned_message}\""
    if current_draft:
        user_prompt += f"\nCurrent Draft Context:\n{json.dumps(current_draft, default=str)}"

    result: Optional[ExtractionPayload] = None

    if chosen_provider in ["hybrid", "hybrid_local", "option2"]:
        from invoicemate.services.hybrid_extractor import extract_intent_hybrid
        result = extract_intent_hybrid(cleaned_message, current_draft=current_draft)
    elif chosen_provider == "claude":
        result = _call_claude_api(user_prompt)
    elif chosen_provider == "gemini":
        result = _call_gemini_api(user_prompt)

    # Fallback to rule engine if API is unavailable, failed, or malformed
    if not result:
        result = RuleBasedFallbackExtractor.extract(cleaned_message, current_draft=current_draft)

    # Confidence gating mandate (TASK.md Section 2):
    # Must achieve intent confidence >= 0.75. Below threshold -> route to clarify_needed.
    if result.confidence < CONFIDENCE_THRESHOLD:
        return ExtractionPayload(
            intent=IntentEnum.CLARIFY_NEEDED,
            confidence=result.confidence,
            customer_name=result.customer_name,
            items=result.items,
            clarification_question=result.clarification_question or "I am not completely sure. Could you please clarify the customer or items for this invoice?",
        )

    return _normalize_extraction_result(result)

