import logging
from typing import Dict, Any, Optional, Tuple, List
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from invoicemate.models.enums import DraftState, IntentEnum, InvoiceStatus
from invoicemate.models.draft import Draft
from invoicemate.models.invoice import Invoice
from invoicemate.services.customer_service import (
    resolve_customer_name,
    get_customer_by_id,
    create_customer,
)
from invoicemate.services.invoice_engine import (
    create_draft,
    update_draft,
    confirm_invoice,
    cancel_draft,
    cancel_invoice,
    search_invoices,
    mark_as_paid,
    get_invoice_by_number,
)
from invoicemate.services.llm_extractor import extract_intent
from invoicemate.schemas.customer import CustomerCreate

logger = logging.getLogger(__name__)


def get_active_draft(db: Session, org_id: int, chat_id: str) -> Optional[Draft]:
    """Retrieve currently active draft for (org_id, chat_id)."""
    stmt = (
        select(Draft)
        .where(
            and_(
                Draft.org_id == org_id,
                Draft.chat_id == str(chat_id),
                Draft.state.in_([
                    DraftState.DRAFTING.value,
                    DraftState.WAITING_FOR_CUSTOMER_SELECTION.value,
                    DraftState.WAITING_FOR_CONFIRMATION.value,
                ]),
            )
        )
        .order_by(Draft.updated_at.desc())
    )
    return db.scalars(stmt).first()


def get_session_state(db: Session, org_id: int, chat_id: str) -> Tuple[str, Optional[Draft]]:
    """Return persistent state tuple (state, active_draft)."""
    draft = get_active_draft(db, org_id=org_id, chat_id=chat_id)
    if draft:
        return draft.state, draft
    return DraftState.IDLE.value, None


def process_incoming_message(
    db: Session, org_id: int, chat_id: str, message_text: str, provider: Optional[str] = None
) -> Dict[str, Any]:
    """
    Central Conversation Broker:
    Receives incoming natural language message, evaluates against current session state tuple
    (chat_id, org_id, state, active_draft_id), coordinates extraction, and invokes deterministic business logic.
    """
    state, active_draft = get_session_state(db, org_id=org_id, chat_id=chat_id)
    text = message_text.strip()

    # Draft context if active
    draft_context = None
    if active_draft and active_draft.draft_json:
        draft_context = {
            "id": active_draft.id,
            "customer_name": active_draft.draft_json.get("customer_name"),
            "currency": active_draft.draft_json.get("currency", "USD"),
            "items": active_draft.draft_json.get("items", []),
        }

    # State: WAITING_FOR_CUSTOMER_SELECTION
    if state == DraftState.WAITING_FOR_CUSTOMER_SELECTION.value and active_draft:
        # Check if user sent a customer ID or name directly
        target_cust = None
        if text.isdigit():
            target_cust = get_customer_by_id(db, int(text), org_id=org_id)

        if not target_cust:
            resolved, _ = resolve_customer_name(db, org_id=org_id, name_query=text)
            target_cust = resolved

        if target_cust:
            updated = update_draft(db, draft_id=active_draft.id, org_id=org_id, customer_id=target_cust.id)
            return {
                "action": "draft_updated",
                "state": DraftState.WAITING_FOR_CONFIRMATION.value,
                "draft": updated,
                "message": f"Customer '{target_cust.name}' selected.",
            }
        else:
            return {
                "action": "customer_disambiguation_retry",
                "state": DraftState.WAITING_FOR_CUSTOMER_SELECTION.value,
                "draft": active_draft,
                "message": f"Customer '{text}' could not be uniquely resolved. Please pick from the list.",
            }

    # Extract intent through LLM / Hybrid service
    extraction = extract_intent(text, current_draft=draft_context, provider=provider)

    # 1. CONFIRM
    if extraction.intent == IntentEnum.CONFIRM:
        if not active_draft:
            return {
                "action": "no_active_draft",
                "state": DraftState.IDLE.value,
                "message": "No active draft to confirm. You can create one anytime by describing your invoice.",
            }

        try:
            invoice = confirm_invoice(db, draft_id=active_draft.id, org_id=org_id)
            return {
                "action": "invoice_confirmed",
                "state": DraftState.SENT.value,
                "invoice": invoice,
                "message": f"Invoice #{invoice.invoice_number} successfully confirmed and issued!",
            }
        except Exception as err:
            logger.error(f"Invoice confirmation error: {err}")
            return {
                "action": "confirmation_failed",
                "state": DraftState.PDF_FAILED.value,
                "error": str(err),
                "message": f"Invoice confirmation failed: {err}",
            }

    # 2. CANCEL
    elif extraction.intent == IntentEnum.CANCEL:
        if active_draft:
            cancel_draft(db, draft_id=active_draft.id, org_id=org_id)
            return {
                "action": "draft_cancelled",
                "state": DraftState.IDLE.value,
                "message": "Invoice draft has been cancelled. Ready for new requests.",
            }
        return {
            "action": "no_active_draft",
            "state": DraftState.IDLE.value,
            "message": "No active draft to cancel.",
        }

    # 3. SEARCH
    elif extraction.intent == IntentEnum.SEARCH:
        query = extraction.search_query or text
        results = search_invoices(db, org_id=org_id, query=query, limit=10)
        return {
            "action": "search_results",
            "state": state,
            "query": query,
            "invoices": results,
        }

    # 4. UPDATE DRAFT
    elif extraction.intent == IntentEnum.UPDATE_DRAFT:
        if not active_draft:
            return {
                "action": "no_active_draft",
                "state": DraftState.IDLE.value,
                "message": "No active draft found to update. Please describe your invoice first.",
            }

        items_payload = None
        if extraction.items is not None:
            if len(extraction.items) == 0:
                cancel_draft(db, draft_id=active_draft.id, org_id=org_id)
                return {
                    "action": "draft_cancelled",
                    "state": DraftState.IDLE.value,
                    "message": "All items removed. Invoice draft has been cancelled.",
                }
            items_payload = [
                {"name": itm.name, "qty": itm.qty, "price": itm.unit_price}
                for itm in extraction.items
            ]

        updated = update_draft(
            db,
            draft_id=active_draft.id,
            org_id=org_id,
            items=items_payload,
            customer_name=extraction.customer_name,
            currency=extraction.currency,
        )
        return {
            "action": "draft_updated",
            "state": DraftState.WAITING_FOR_CONFIRMATION.value,
            "draft": updated,
            "message": "Draft updated.",
        }

    # 5. CREATE DRAFT
    elif extraction.intent == IntentEnum.CREATE_DRAFT:
        if not extraction.items:
            return {
                "action": "clarify_needed",
                "state": DraftState.DRAFTING.value,
                "message": f"What items and prices should be on the invoice for {extraction.customer_name or 'this customer'}?",
            }

        # Check customer matching
        target_customer = None
        if extraction.customer_name:
            resolved, matches = resolve_customer_name(
                db, org_id=org_id, name_query=extraction.customer_name
            )
            if matches:
                # Multiple customer matches found -> Transition to WAITING_FOR_CUSTOMER_SELECTION
                items_payload = [
                    {"name": itm.name, "qty": itm.qty, "price": itm.unit_price}
                    for itm in extraction.items
                ]
                draft = create_draft(
                    db,
                    org_id=org_id,
                    chat_id=chat_id,
                    items=items_payload,
                    currency=extraction.currency or "USD",
                )
                draft.state = DraftState.WAITING_FOR_CUSTOMER_SELECTION.value
                db.commit()
                db.refresh(draft)

                return {
                    "action": "customer_disambiguation_required",
                    "state": DraftState.WAITING_FOR_CUSTOMER_SELECTION.value,
                    "draft": draft,
                    "matches": matches,
                    "query": extraction.customer_name,
                }
            elif resolved:
                target_customer = resolved

        items_payload = [
            {"name": itm.name, "qty": itm.qty, "price": itm.unit_price}
            for itm in extraction.items
        ]
        draft = create_draft(
            db,
            org_id=org_id,
            chat_id=chat_id,
            items=items_payload,
            customer_id=target_customer.id if target_customer else None,
            customer_name=extraction.customer_name if not target_customer else None,
            currency=extraction.currency or "USD",
        )
        return {
            "action": "draft_created",
            "state": DraftState.WAITING_FOR_CONFIRMATION.value,
            "draft": draft,
        }

    # 6. GREETING
    elif extraction.intent == IntentEnum.GREETING:
        greeting_msg = (
            "<b>សួស្ដី! / Hello!</b>\n\n"
            "ខ្ញុំជា <b>InvoiceMate</b> ជំនួយការបង្កើត និងគ្រប់គ្រងវិក្កយបត្រឆ្លាតវៃរបស់អ្នក។\n"
            "I'm <b>InvoiceMate</b>, your smart AI invoicing assistant.\n\n"
            "<b>អ្នកអាចបង្កើតវិក្កយបត្របានភ្លាមៗ / You can create an invoice anytime:</b>\n"
            "• <code>Invoice Sokha 2 monitors at $450 each</code>\n"
            "• <code>ធ្វើ invoice ឲ្យ Dara $50 សម្រាប់ website design</code>\n"
            "• <code>គិតលុយ Bopha: 5 coffee bags $12 each</code>\n\n"
            "ឬវាយបញ្ជា /help ដើម្បីមើលមុខងារទាំងអស់! / Or type /help to see all commands!\n\n"
            "<b>Developer:</b> <a href=\"https://github.com/DararithJ369/DararithJ369/\">Dararith J.</a>"
        )
        return {
            "action": "greeting",
            "state": state,
            "message": greeting_msg,
        }

    # 7. THANKS
    elif extraction.intent == IntentEnum.THANKS:
        return {
            "action": "thanks",
            "state": state,
            "message": "<b>រីករាយដែលបានជួយ! / You're very welcome!</b>\nប្រសិនបើអ្នកត្រូវការបង្កើត ឬស្វែងរកវិក្កយបត្រផ្សេងទៀត សូមប្រាប់ខ្ញុំបានគ្រប់ពេល។",
        }

    # 8. HELP
    elif extraction.intent == IntentEnum.HELP:
        help_msg = (
            "<b>ជំនួយការ InvoiceMate / User Guide:</b>\n\n"
            "<b>1. បង្កើតវិក្កយបត្រ / Create Invoice:</b>\n"
            "• <code>Invoice Sokha 2 monitors at $450 each</code>\n"
            "• <code>គិតលុយ Dara: 1 laptop $800, 1 mouse $25</code>\n\n"
            "<b>2. កែប្រែវិក្កយបត្រព្រាង / Update Draft:</b>\n"
            "• <code>actually make it 3 monitors</code>\n"
            "• <code>change quantity of airpods to 4</code>\n"
            "• <code>add 1 keyboard for $25</code>\n\n"
            "<b>3. បញ្ជាក់ និងទទួល PDF / Confirm & Download:</b>\n"
            "• ចុចប៊ូតុង [បញ្ជាក់ / Confirm] ឬវាយពាក្យ <code>យល់ព្រម</code>\n\n"
            "<b>4. ស្វែងរកប្រវត្តិ / Search History:</b>\n"
            "• <code>find Dara invoice</code> ឬវាយបញ្ជា /invoices"
        )
        return {
            "action": "help",
            "state": state,
            "message": help_msg,
        }

    # 9. CLARIFY NEEDED
    elif extraction.intent == IntentEnum.CLARIFY_NEEDED:
        return {
            "action": "clarify_needed",
            "state": state,
            "message": extraction.clarification_question or "Could you please clarify customer and items for this invoice?",
        }

    return {
        "action": "unknown",
        "state": state,
        "message": "I didn't quite catch that. Could you please specify customer and items? (e.g. <code>Invoice Sokha 2 monitors at $450 each</code>)",
    }



def process_callback_query(
    db: Session, org_id: int, chat_id: str, callback_data: str
) -> Dict[str, Any]:
    """
    Handle inline button callbacks according to state machine rules:
    - cb_confirm_draft:{draft_id} -> CONFIRMED
    - cb_edit_draft:{draft_id} -> prompts for edits
    - cb_cancel_draft:{draft_id} -> IDLE
    - select_cust:{customer_id} -> resolves customer
    - mark_paid:{invoice_id} -> PAID
    """
    parts = callback_data.split(":")
    action_prefix = parts[0]
    target_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None

    if action_prefix in ["cb_confirm_draft", "confirm_inv"] and target_id:
        try:
            inv = confirm_invoice(db, draft_id=target_id, org_id=org_id)
            return {
                "action": "invoice_confirmed",
                "state": DraftState.SENT.value,
                "invoice": inv,
                "message": f"Invoice #{inv.invoice_number} confirmed!",
            }
        except Exception as err:
            return {
                "action": "confirmation_failed",
                "state": DraftState.PDF_FAILED.value,
                "error": str(err),
            }

    elif action_prefix in ["cb_cancel_draft", "cancel_inv"] and target_id:
        draft = cancel_draft(db, draft_id=target_id, org_id=org_id)
        return {
            "action": "draft_cancelled",
            "state": DraftState.IDLE.value,
            "message": f"Draft #{draft.id} cancelled.",
        }

    elif action_prefix in ["select_cust"] and target_id:
        cust = get_customer_by_id(db, target_id, org_id=org_id)
        active_draft = get_active_draft(db, org_id=org_id, chat_id=chat_id)
        if active_draft and cust:
            updated = update_draft(db, draft_id=active_draft.id, org_id=org_id, customer_id=cust.id)
            return {
                "action": "draft_updated",
                "state": DraftState.WAITING_FOR_CONFIRMATION.value,
                "draft": updated,
                "message": f"Selected customer: {cust.name}",
            }

    elif action_prefix in ["mark_paid", "cb_mark_paid"] and target_id:
        paid_inv = mark_as_paid(db, invoice_id=target_id, org_id=org_id)
        return {
            "action": "marked_paid",
            "state": DraftState.PAID.value,
            "invoice": paid_inv,
            "message": f"Invoice #{paid_inv.invoice_number} marked as PAID.",
        }

    elif action_prefix in ["cb_check_payment", "check_payment"] and target_id:
        from invoicemate.services.bakong_webhook_service import reconcile_invoice_by_inquiry
        status, inv = reconcile_invoice_by_inquiry(db, invoice_id=target_id)
        if status == "settled":
            return {
                "action": "payment_inquiry_settled",
                "invoice": inv,
                "message": f"Payment for invoice #{inv.invoice_number} verified via Bakong!",
            }
        elif status == "already_paid":
            return {
                "action": "payment_inquiry_already_paid",
                "invoice": inv,
                "message": f"Invoice #{inv.invoice_number} is already paid.",
            }
        else:
            return {
                "action": "payment_inquiry_pending",
                "invoice": inv,
                "message": f"Payment for invoice #{inv.invoice_number} is still pending. Customer has not completed the transfer yet.",
            }

    return {"action": "unhandled", "data": callback_data}
