import logging
import os
import re
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile

from invoicemate.core.config import settings
from invoicemate.db.session import SessionLocal
from invoicemate.services.org_service import get_or_create_org
from invoicemate.services.conversation_service import (
    process_incoming_message,
    process_callback_query,
    get_session_state,
)
from invoicemate.services.invoice_engine import (
    get_invoice_history,
    get_invoice_by_number,
    mark_as_paid,
    cancel_draft,
)
from invoicemate.bot.card_formatter import format_invoice_card, get_draft_keyboard
from invoicemate.bot.gifs import send_event_gif

logger = logging.getLogger(__name__)
router = Router()


def _get_org_for_user(db, telegram_user) -> int:
    """Resolve or auto-register organization for Telegram account."""
    uid = str(telegram_user.id)
    name = telegram_user.full_name or telegram_user.username or "Merchant"
    org = get_or_create_org(db, telegram_user_id=uid, business_name=name)
    return org.id


def _format_history_list(invoices, title="ប្រវត្តិវិក្កយបត្រ / INVOICE HISTORY"):
    if not invoices:
        return f"<b>{title}</b>\n\nNo invoices found."

    lines = [f"<b>{title}</b>\n──────────────────────────────"]

    for inv in invoices:
        cust_name = inv.customer.name if inv.customer else "Unknown Customer"
        symbol = "$" if inv.currency == "USD" else "៛"
        date_str = inv.created_at.strftime("%Y-%m-%d") if getattr(inv, "created_at", None) else "N/A"
        lines.append(
            f"• <b>{inv.invoice_number}</b> — {cust_name}\n"
            f"   កាលបរិច្ឆេទ / Date: <code>{date_str}</code>\n"
            f"   Total: <b>{symbol}{inv.total:,.2f} {inv.currency}</b> | Status: <code>[{inv.status.upper()}]</code>\n"
            f"   Download: <code>/pdf {inv.invoice_number}</code>"
        )
        if inv.status == "sent":
            lines.append(f"   To mark paid: <code>/paid {inv.invoice_number}</code>")
        lines.append("")

    return "\n".join(lines)


@router.message(Command("start"))
async def handle_start_command(message: Message):
    user_name = (
        f"@{message.from_user.username}"
        if (message.from_user and message.from_user.username)
        else (message.from_user.first_name if (message.from_user and message.from_user.first_name) else "there")
    )
    welcome_text = (
        f"<b>សួស្ដី! / Hello, {user_name}!</b>\n\n"
        "ខ្ញុំជា <b>InvoiceMate</b> ជំនួយការបង្កើត និងគ្រប់គ្រងវិក្កយបត្រឆ្លាតវៃរបស់អ្នក។\n"
        "I'm <b>InvoiceMate</b>, your smart AI invoicing assistant.\n\n"
        "<b>ពាក្យបញ្ជា / Available Commands:</b>\n"
        "• /create — How to create a multi-item invoice\n"
        "• /invoices — List recent invoice history & PDF links\n"
        "• /status — Check status of invoices\n"
        "• /paid <code>[INV-NUMBER]</code> — Mark an invoice as paid\n"
        "• /clear — Clear active draft\n"
        "• /help — Show this help guide\n\n"
        "<b>ឧទាហរណ៍ / Natural Language Examples:</b>\n"
        "• <code>Invoice Sokha 2 monitors at $450 each</code>\n"
        "• <code>គិតលុយ Dara: 1 laptop $800, 1 mouse $25</code>\n"
        "• <code>actually make it 3 monitors</code>\n"
        "• <code>find Dara invoice</code>\n\n"
        "<b>Developer:</b> <a href=\"https://github.com/DararithJ369/DararithJ369/\">Dararith J.</a>"
    )
    await send_event_gif(message, "welcome", caption=welcome_text)


@router.message(Command("help"))
async def handle_help_command(message: Message):
    help_text = (
        "<b>ពាក្យបញ្ជា / Available Commands:</b>\n"
        "• /create — How to create a multi-item invoice\n"
        "• /invoices — List recent invoice history & PDF links\n"
        "• /status — Check status of invoices\n"
        "• /paid <code>[INV-NUMBER]</code> — Mark an invoice as paid\n"
        "• /clear — Clear active draft\n"
        "• /help — Show this help guide\n\n"
        "<b>ឧទាហរណ៍ / Natural Language Examples:</b>\n"
        "• <code>Invoice Sokha 2 monitors at $450 each</code>\n"
        "• <code>គិតលុយ Dara: 1 laptop $800, 1 mouse $25</code>\n"
        "• <code>actually make it 3 monitors</code>\n"
        "• <code>find Dara invoice</code>"
    )
    await message.answer(help_text, parse_mode="HTML")


@router.message(Command("create"))
async def handle_create_command(message: Message):
    guide_text = (
        "<b>របៀបបង្កើតវិក្កយបត្រ / How to Create an Invoice:</b>\n\n"
        "<b>Single item:</b>\n"
        "<code>Invoice Sokha 2 monitors at $450 each</code>\n\n"
        "<b>Multiple items:</b>\n"
        "<code>Invoice Sokha: 2 monitors at $450 each, 1 keyboard for $25</code>\n\n"
        "<b>Khmer script / Code-switching:</b>\n"
        "<code>គិតលុយ Dara: ២ monitors តម្លៃ $450</code>"
    )
    await message.answer(guide_text, parse_mode="HTML")


@router.message(Command("clear"))
async def handle_clear_command(message: Message):
    with SessionLocal() as db:
        org_id = _get_org_for_user(db, message.from_user)
        chat_id = str(message.chat.id)
        state, draft = get_session_state(db, org_id=org_id, chat_id=chat_id)
        if draft:
            cancel_draft(db, draft_id=draft.id, org_id=org_id)
            await send_event_gif(
                message,
                "clear",
                caption=f"Active draft <b>#{draft.id}</b> cleared! Ready for new invoices.",
            )
        else:
            await send_event_gif(
                message,
                "clear",
                caption="No active draft to clear. You can create an invoice anytime!",
            )


@router.message(Command("status"))
async def handle_status_command(message: Message):
    text = message.text.strip()
    parts = text.split()

    with SessionLocal() as db:
        org_id = _get_org_for_user(db, message.from_user)
        if len(parts) > 1:
            inv_num = parts[1].strip()
            inv = get_invoice_by_number(db, inv_num, org_id=org_id)
            if not inv:
                await message.answer(f"Invoice '{inv_num}' not found.")
                return
            card_text = format_invoice_card(inv, title=f"INVOICE STATUS — {inv.invoice_number}")
            await message.answer(card_text, parse_mode="HTML")
            return

        all_invoices = get_invoice_history(db, org_id=org_id, timeframe="all", limit=50)
        sent = [i for i in all_invoices if i.status == "sent"]
        paid = [i for i in all_invoices if i.status == "paid"]
        cancelled = [i for i in all_invoices if i.status == "cancelled"]

        summary = (
            "<b>INVOICE STATUS SUMMARY</b>\n"
            "──────────────────────────────\n"
            f"• <b>Sent (Unpaid):</b> {len(sent)}\n"
            f"• <b>Paid:</b> {len(paid)}\n"
            f"• <b>Cancelled:</b> {len(cancelled)}\n"
            "──────────────────────────────\n"
            "<i>Use <code>/invoices</code> to view details or <code>/paid [INV-NUMBER]</code> to mark paid.</i>"
        )
        await message.answer(summary, parse_mode="HTML")


@router.message(Command("invoices", "history"))
async def handle_history_command(message: Message):
    with SessionLocal() as db:
        org_id = _get_org_for_user(db, message.from_user)
        invoices = get_invoice_history(db, org_id=org_id, timeframe="all", limit=10)
        history_text = _format_history_list(invoices, title="RECENT INVOICES")

        buttons = []
        for inv in invoices[:5]:
            row_buttons = [
                InlineKeyboardButton(text=f"PDF #{inv.invoice_number}", callback_data=f"dl_pdf:{inv.invoice_number}")
            ]
            if inv.status == "sent":
                row_buttons.append(InlineKeyboardButton(text="Mark Paid", callback_data=f"mark_paid:{inv.id}"))
            buttons.append(row_buttons)

        kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
        await message.answer(history_text, reply_markup=kb, parse_mode="HTML")


@router.message(Command("pdf", "download", "get_pdf"))
async def handle_get_pdf_command(message: Message):
    text = message.text.strip()
    parts = text.split()
    if len(parts) < 2:
        await message.answer("Usage: <code>/pdf INV-000001</code>", parse_mode="HTML")
        return

    inv_num = parts[1].strip().upper()
    with SessionLocal() as db:
        org_id = _get_org_for_user(db, message.from_user)
        inv = get_invoice_by_number(db, inv_num, org_id=org_id)
        if not inv:
            await message.answer(f"Invoice '{inv_num}' not found.")
            return

        local_path = os.path.join(settings.STORAGE_DIR, f"{inv.invoice_number}.pdf")
        if not os.path.exists(local_path):
            from invoicemate.services.pdf_generator import generate_invoice_pdf
            local_path = generate_invoice_pdf(inv, output_dir=settings.STORAGE_DIR)

        if os.path.exists(local_path):
            pdf_file = FSInputFile(local_path)
            symbol = "$" if inv.currency == "USD" else "៛"
            cust_name = inv.customer.name if inv.customer else "N/A"
            await message.answer_document(
                document=pdf_file,
                caption=f"<b>វិក្កយបត្រ / Invoice #{inv.invoice_number}</b>\nCustomer: {cust_name}\nTotal: {symbol}{inv.total:,.2f} {inv.currency}\nStatus: {inv.status.upper()}",
                parse_mode="HTML",
            )
        else:
            await message.answer("Could not generate PDF document.")


@router.message(Command("paid"))
async def handle_mark_paid_command(message: Message):
    text = message.text.strip()
    parts = text.split()
    if len(parts) < 2:
        await message.answer("Usage: <code>/paid INV-000001</code>", parse_mode="HTML")
        return

    inv_num = parts[1].strip()
    with SessionLocal() as db:
        org_id = _get_org_for_user(db, message.from_user)
        inv = get_invoice_by_number(db, inv_num, org_id=org_id)
        if not inv:
            await message.answer(f"Invoice '{inv_num}' not found.")
            return

        try:
            paid_inv = mark_as_paid(db, inv.id, org_id=org_id)
            await send_event_gif(
                message,
                "paid",
                caption=f"Invoice <b>{paid_inv.invoice_number}</b> marked as <b>PAID</b>!",
            )
        except Exception as err:
            await message.answer(f"Error: {err}")


@router.message(F.text)
async def handle_natural_language_message(message: Message):
    user_text = message.text.strip()
    if not user_text or user_text.startswith("/"):
        return

    chat_id = str(message.chat.id)

    # Quick check for direct natural language PDF request (e.g. "download INV-000002")
    pdf_req = re.search(r"\b(?:pdf|download|get\s+pdf|ទាញយក|ផ្ញើ)\s+(?:invoice\s+|វិក្កយបត្រ\s*)?(inv-\d+)\b", user_text, re.IGNORECASE)
    if pdf_req:
        inv_num = pdf_req.group(1).upper()
        with SessionLocal() as db:
            org_id = _get_org_for_user(db, message.from_user)
            inv = get_invoice_by_number(db, inv_num, org_id=org_id)
            if inv:
                local_path = os.path.join(settings.STORAGE_DIR, f"{inv.invoice_number}.pdf")
                if not os.path.exists(local_path):
                    from invoicemate.services.pdf_generator import generate_invoice_pdf
                    local_path = generate_invoice_pdf(inv, output_dir=settings.STORAGE_DIR)
                if os.path.exists(local_path):
                    pdf_file = FSInputFile(local_path)
                    symbol = "$" if inv.currency == "USD" else "៛"
                    cust_name = inv.customer.name if inv.customer else "N/A"
                    await message.answer_document(
                        document=pdf_file,
                        caption=f"<b>វិក្កយបត្រ / Invoice #{inv.invoice_number}</b>\nCustomer: {cust_name}\nTotal: {symbol}{inv.total:,.2f} {inv.currency}\nStatus: {inv.status.upper()}",
                        parse_mode="HTML",
                    )
                    return

    with SessionLocal() as db:
        org_id = _get_org_for_user(db, message.from_user)

        res = process_incoming_message(
            db=db,
            org_id=org_id,
            chat_id=chat_id,
            message_text=user_text,
        )

        action = res.get("action")

        if action in ["draft_created", "draft_updated"]:
            draft = res["draft"]
            card_text = format_invoice_card(draft, title="វិក្កយបត្រព្រាង / INVOICE DRAFT")
            await message.answer(
                card_text,
                reply_markup=get_draft_keyboard(draft.id),
                parse_mode="HTML",
            )

        elif action == "customer_disambiguation_required":
            matches = res["matches"]
            buttons = [
                [InlineKeyboardButton(text=c.name, callback_data=f"select_cust:{c.id}")]
                for c in matches
            ]
            kb = InlineKeyboardMarkup(inline_keyboard=buttons)
            await message.answer(
                f"<b>មានអតិថិជនច្រើនដែលត្រូវគ្នានឹង '{res['query']}':</b>\nសូមជ្រើសរើសអតិថិជន / Please select customer:",
                reply_markup=kb,
                parse_mode="HTML",
            )

        elif action == "customer_disambiguation_retry":
            await message.answer(res.get("message", "Could not resolve customer."))

        elif action == "invoice_confirmed":
            inv = res["invoice"]
            await send_event_gif(message, "success")
            card_text = format_invoice_card(inv, title="វិក្កយបត្រចេញរួចរាល់ / INVOICE ISSUED")
            paid_kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="បានបង់ប្រាក់ / Mark as Paid", callback_data=f"mark_paid:{inv.id}")]
                ]
            )
            await message.answer(card_text, reply_markup=paid_kb, parse_mode="HTML")

            local_path = os.path.join(settings.STORAGE_DIR, f"{inv.invoice_number}.pdf")
            if os.path.exists(local_path):
                pdf_file = FSInputFile(local_path)
                await message.answer_document(
                    document=pdf_file,
                    caption=f"<b>PDF #{inv.invoice_number}</b>\n<a href=\"{inv.pdf_url}\">តំណភ្ជាប់ PDF / Public Link</a>",
                    parse_mode="HTML",
                )

        elif action == "confirmation_failed":
            await message.answer(f"<b>ការចេញវិក្កយបត្របរាជ័យ / Generation Failed:</b>\n{res.get('message')}", parse_mode="HTML")

        elif action == "draft_cancelled":
            await send_event_gif(message, "clear", caption="<b>វិក្កយបត្រព្រាងត្រូវបានបោះបង់ / Draft Cancelled.</b>")

        elif action == "search_results":
            history_text = _format_history_list(res["invoices"], title=f"លទ្ធផលស្វែងរក / RESULTS FOR '{res['query']}'")
            await message.answer(history_text, parse_mode="HTML")

        elif action == "greeting":
            user_name = (
                f"@{message.from_user.username}"
                if (message.from_user and message.from_user.username)
                else (message.from_user.first_name if (message.from_user and message.from_user.first_name) else "there")
            )
            msg = res.get("message", "")
            if "Hello!" in msg:
                msg = msg.replace("Hello!", f"Hello, {user_name}!")
            await send_event_gif(message, "welcome", caption=msg)

        elif action == "thanks":
            await message.answer(res.get("message"), parse_mode="HTML")

        elif action == "help":
            await message.answer(res.get("message"), parse_mode="HTML")

        elif action == "clarify_needed":
            await message.answer(f"{res.get('message')}", parse_mode="HTML")

        elif action == "no_active_draft":
            await message.answer(res.get("message", "No active draft."))

        else:
            await message.answer(res.get("message", "Please specify customer and items."), parse_mode="HTML")


@router.callback_query(F.data.startswith("select_cust:"))
async def handle_select_cust_cb(callback: CallbackQuery):
    with SessionLocal() as db:
        org_id = _get_org_for_user(db, callback.from_user)
        chat_id = str(callback.message.chat.id)
        res = process_callback_query(db, org_id=org_id, chat_id=chat_id, callback_data=callback.data)
        if res.get("action") == "draft_updated":
            draft = res["draft"]
            card_text = format_invoice_card(draft, title="វិក្កយបត្រព្រាងកែប្រែ / UPDATED DRAFT")
            await callback.message.edit_text(card_text, reply_markup=get_draft_keyboard(draft.id), parse_mode="HTML")
            await callback.answer(res.get("message", "Customer selected."))
        else:
            await callback.answer("Selected.")


@router.callback_query(F.data.startswith("cb_confirm_draft:") | F.data.startswith("confirm_inv:"))
async def handle_confirm_draft_cb(callback: CallbackQuery):
    with SessionLocal() as db:
        org_id = _get_org_for_user(db, callback.from_user)
        chat_id = str(callback.message.chat.id)
        res = process_callback_query(db, org_id=org_id, chat_id=chat_id, callback_data=callback.data)

        if res.get("action") == "invoice_confirmed":
            inv = res["invoice"]
            await send_event_gif(callback.message, "success")
            card_text = format_invoice_card(inv, title="វិក្កយបត្រចេញរួចរាល់ / INVOICE ISSUED")
            paid_kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="បានបង់ប្រាក់ / Mark as Paid", callback_data=f"mark_paid:{inv.id}")]
                ]
            )
            await callback.message.edit_text(card_text, reply_markup=paid_kb, parse_mode="HTML")
            await callback.answer("Invoice confirmed!")

            local_path = os.path.join(settings.STORAGE_DIR, f"{inv.invoice_number}.pdf")
            if os.path.exists(local_path):
                pdf_file = FSInputFile(local_path)
                await callback.message.answer_document(
                    document=pdf_file,
                    caption=f"<b>PDF #{inv.invoice_number}</b>\n<a href=\"{inv.pdf_url}\">តំណភ្ជាប់ PDF / Public Link</a>",
                    parse_mode="HTML",
                )
        else:
            await callback.answer(f"Failed: {res.get('error')}", show_alert=True)


@router.callback_query(F.data.startswith("cb_cancel_draft:") | F.data.startswith("cancel_inv:"))
async def handle_cancel_draft_cb(callback: CallbackQuery):
    with SessionLocal() as db:
        org_id = _get_org_for_user(db, callback.from_user)
        chat_id = str(callback.message.chat.id)
        res = process_callback_query(db, org_id=org_id, chat_id=chat_id, callback_data=callback.data)
        await send_event_gif(callback.message, "clear", caption="<b>វិក្កយបត្រព្រាងត្រូវបានបោះបង់ / Draft Cancelled.</b>")
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.answer("Draft cancelled.")


@router.callback_query(F.data.startswith("mark_paid:"))
async def handle_mark_paid_cb(callback: CallbackQuery):
    with SessionLocal() as db:
        org_id = _get_org_for_user(db, callback.from_user)
        chat_id = str(callback.message.chat.id)
        res = process_callback_query(db, org_id=org_id, chat_id=chat_id, callback_data=callback.data)
        if res.get("action") == "marked_paid":
            inv = res["invoice"]
            await send_event_gif(callback.message, "paid", caption=f"Invoice <b>{inv.invoice_number}</b> marked as <b>PAID</b>!")
            card_text = format_invoice_card(inv, title="វិក្កយបត្របានទូទាត់រួច / INVOICE PAID")
            await callback.message.edit_text(card_text, parse_mode="HTML")
            await callback.answer("Marked as PAID!")
        else:
            await callback.answer("Update failed.")


@router.callback_query(F.data.startswith("dl_pdf:"))
async def handle_dl_pdf_cb(callback: CallbackQuery):
    inv_num = callback.data.split(":")[1].strip().upper()
    with SessionLocal() as db:
        org_id = _get_org_for_user(db, callback.from_user)
        inv = get_invoice_by_number(db, inv_num, org_id=org_id)
        if not inv:
            await callback.answer(f"Invoice '{inv_num}' not found.", show_alert=True)
            return

        local_path = os.path.join(settings.STORAGE_DIR, f"{inv.invoice_number}.pdf")
        if not os.path.exists(local_path):
            from invoicemate.services.pdf_generator import generate_invoice_pdf
            local_path = generate_invoice_pdf(inv, output_dir=settings.STORAGE_DIR)

        if os.path.exists(local_path):
            pdf_file = FSInputFile(local_path)
            symbol = "$" if inv.currency == "USD" else "៛"
            cust_name = inv.customer.name if inv.customer else "N/A"
            await callback.message.answer_document(
                document=pdf_file,
                caption=f"<b>វិក្កយបត្រ / Invoice #{inv.invoice_number}</b>\nCustomer: {cust_name}\nTotal: {symbol}{inv.total:,.2f} {inv.currency}\nStatus: {inv.status.upper()}",
                parse_mode="HTML",
            )
            await callback.answer("PDF sent!")
        else:
            await callback.answer("Could not generate PDF document.", show_alert=True)

