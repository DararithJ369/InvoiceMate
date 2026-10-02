from decimal import Decimal
from invoicemate.db import init_db, SessionLocal
from invoicemate.services.org_service import get_or_create_org
from invoicemate.services.conversation_service import (
    process_incoming_message,
    process_callback_query,
    get_session_state,
)
from invoicemate.services.invoice_engine import search_invoices


def run_demo():
    print("🚀 --- InvoiceAI / InvoiceMate End-to-End Execution Demo --- 🚀\n")

    init_db()

    with SessionLocal() as db:
        # Step 0: Ensure multi-tenant Org exists
        org = get_or_create_org(
            db,
            telegram_user_id="demo_merchant_kh",
            business_name="Angkor Tech & Coffee Shop",
            phone="+85512345678",
        )
        chat_id = "chat_demo_2026"
        print(f"0. Organization initialized: {org.business_name} (ID: {org.id})\n")

        # Step 1: User sends natural language message to create invoice
        msg1 = "Invoice Sokha 2 monitors at $450 each"
        print(f"1. User message: '{msg1}'")

        res1 = process_incoming_message(db, org_id=org.id, chat_id=chat_id, message_text=msg1)
        draft = res1["draft"]
        print(f"   Action: {res1['action']} | State: {res1['state']}")
        print(f"   Draft Created ID: #{draft.id}")
        print(f"   Customer: {draft.draft_json.get('customer_name')}")
        print(f"   Subtotal: ${draft.draft_json.get('subtotal'):,.2f} {draft.draft_json.get('currency')}\n")

        # Step 2: User makes a correction ("actually make it 3 monitors and add 1 keyboard for $25")
        msg2 = "actually make it 3 monitors and add 1 keyboard for $25"
        print(f"2. User correction: '{msg2}'")

        res2 = process_incoming_message(db, org_id=org.id, chat_id=chat_id, message_text=msg2)
        updated_draft = res2["draft"]
        print(f"   Action: {res2['action']} | State: {res2['state']}")
        print(f"   Updated Subtotal: ${updated_draft.draft_json.get('subtotal'):,.2f} USD")
        print(f"   Updated Items Count: {len(updated_draft.draft_json.get('items'))}\n")

        # Step 3: User confirms invoice -> status = 'sent' + PDF invoice generated with Bakong KHQR
        print("3. Confirming invoice via inline callback...")
        res3 = process_callback_query(
            db,
            org_id=org.id,
            chat_id=chat_id,
            callback_data=f"cb_confirm_draft:{updated_draft.id}",
        )
        invoice = res3["invoice"]
        print(f"   Action: {res3['action']} | State: {res3['state']}")
        print(f"   Assigned Invoice Number: {invoice.invoice_number}")
        print(f"   Status: {invoice.status.upper()} | PDF Status: {invoice.pdf_status.upper()}")
        print(f"   Public PDF URL: {invoice.pdf_url}\n")

        # Step 4: Mark as Paid
        print("4. Marking invoice as PAID via callback...")
        res4 = process_callback_query(
            db,
            org_id=org.id,
            chat_id=chat_id,
            callback_data=f"mark_paid:{invoice.id}",
        )
        paid_inv = res4["invoice"]
        print(f"   Status: {paid_inv.status.upper()} | Paid At: {paid_inv.paid_at}\n")

        # Step 5: Search & History
        print("5. Searching history for 'Sokha':")
        results = search_invoices(db, org_id=org.id, query="Sokha")
        for inv in results:
            print(f"   • {inv.invoice_number} | Customer: {inv.customer.name} | Total: ${inv.total:,.2f} | Status: {inv.status.upper()}")

    print("\n✅ --- Demo Completed Successfully with Zero Errors! --- ✅")


if __name__ == "__main__":
    run_demo()
