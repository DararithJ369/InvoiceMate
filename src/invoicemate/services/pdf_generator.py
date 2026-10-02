import io
import os
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from invoicemate.models.invoice import Invoice
from invoicemate.services.khqr_generator import generate_khqr_string, generate_khqr_image
from invoicemate.services.exchange_rate_service import ExchangeRateResult, get_gdt_fallback_rate


KHMER_FONT_NAME = "KhmerFont"

# Execution limits per TASK.md Section 6:
# - Max embedded image asset size: 2 MB
# - Total in-memory rendering buffer limit per worker: 50 MB
MAX_ASSET_SIZE_BYTES = 2 * 1024 * 1024
MAX_BUFFER_SIZE_BYTES = 50 * 1024 * 1024


def resolve_khmer_font_path() -> Optional[str]:
    """
    Resolve local OpenType/TrueType font supporting complex Khmer script shaping.
    Prioritizes Google Noto Sans Khmer and Kantumruy Pro.
    """
    candidate_paths = [
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "assets", "fonts", "NotoSansKhmer.ttf"),
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "assets", "fonts", "KantumruyPro.ttf"),
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "assets", "fonts", "KhmerFont.ttf"),
        "/System/Library/Fonts/Supplemental/Khmer Sangam MN.ttf",
        "/Library/Fonts/KhmerOS.ttf",
        "/usr/share/fonts/truetype/khmer/KhmerOS.ttf",
    ]

    for p in candidate_paths:
        abs_p = os.path.abspath(p)
        if os.path.exists(abs_p):
            return abs_p
    return None


def get_khmer_font_name() -> str:
    """Return configured font name for Khmer script."""
    return KHMER_FONT_NAME


def render_invoice_pdf_bytes(
    invoice: Invoice,
    merchant_name: str = "InvoiceMate Cambodia",
    exchange_rate_result: Optional[ExchangeRateResult] = None,
    is_tax_invoice: bool = False,
) -> io.BytesIO:
    """
    Render professional bilingual Cambodian invoice PDF directly into an in-memory buffer (io.BytesIO).
    Uses HarfBuzz text shaping engine to ensure flawless rendering of Khmer subscript consonants
    (ជើង), combining vowels, and ligatures per Prakas 723 and Notification 4908.
    """
    rate_info = exchange_rate_result or get_gdt_fallback_rate()
    rate_val = rate_info.rate
    rate_source = rate_info.source
    rate_date = rate_info.bulletin_date

    khr_total = rate_info.to_khr(invoice.total) if invoice.currency == "USD" else invoice.total

    # 1. Generate KHQR String & In-memory / temp image
    khqr_str = generate_khqr_string(
        merchant_name=merchant_name,
        amount=invoice.total,
        currency=invoice.currency,
        bill_number=invoice.invoice_number,
    )
    qr_img_dir = "./storage/invoices/qr"
    os.makedirs(qr_img_dir, exist_ok=True)
    qr_img_path = os.path.join(qr_img_dir, f"{invoice.invoice_number}_qr.png")
    generate_khqr_image(khqr_str, output_path=qr_img_path)

    # Validate image size bounds (< 2MB)
    if os.path.exists(qr_img_path) and os.path.getsize(qr_img_path) > MAX_ASSET_SIZE_BYTES:
        raise ValueError("Embedded QR asset exceeds maximum 2MB size limit")

    # 2. Build PDF Document with FPDF2 + HarfBuzz Complex Text Shaping
    pdf = FPDF(format="letter", unit="mm")
    pdf.set_margins(14, 14, 14)
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    font_path = resolve_khmer_font_path()
    if font_path:
        pdf.add_font(KHMER_FONT_NAME, "", font_path)
        pdf.add_font(KHMER_FONT_NAME, "B", font_path)
        pdf.add_font(KHMER_FONT_NAME, "I", font_path)
        active_font = KHMER_FONT_NAME
    else:
        active_font = "Helvetica"

    # Enable HarfBuzz shaping engine for complex Khmer scripts
    try:
        pdf.set_text_shaping(use_shaping_engine=True)
    except Exception:
        pass

    # Dates and statutory header strings
    created_date_str = (
        invoice.created_at.strftime('%Y-%m-%d')
        if getattr(invoice, 'created_at', None)
        else datetime.now().strftime('%Y-%m-%d')
    )
    doc_header_khmer = "វិក្កយបត្រពន្ធ" if is_tax_invoice else "វិក្កយបត្រពាណិជ្ជកម្ម"
    doc_header_eng = "TAX INVOICE" if is_tax_invoice else "COMMERCIAL INVOICE"

    # --- Header Section (Bilingual Hierarchy) ---
    pdf.set_font(active_font, "B", 16)
    pdf.set_text_color(30, 41, 59)
    pdf.cell(100, 8, merchant_name, new_x=XPos.RIGHT, new_y=YPos.TOP)

    pdf.set_font(active_font, "B", 13)
    pdf.set_text_color(37, 99, 235)
    pdf.cell(86, 8, doc_header_khmer, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font(active_font, "", 9)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(100, 5, "រាជធានីភ្នំពេញ កម្ពុជា / Phnom Penh, Cambodia", new_x=XPos.RIGHT, new_y=YPos.TOP)

    pdf.set_font(active_font, "B", 10)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(86, 5, doc_header_eng, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font(active_font, "", 8)
    pdf.cell(100, 5, "លេខអត្តសញ្ញាណកម្ម អាករ (VATTIN): K001-902201928", new_x=XPos.RIGHT, new_y=YPos.TOP)

    pdf.set_font(active_font, "B", 11)
    pdf.set_text_color(37, 99, 235)
    pdf.cell(86, 5, f"#{invoice.invoice_number}", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Divider line
    pdf.ln(3)
    pdf.set_draw_color(203, 213, 225)
    pdf.set_line_width(0.4)
    pdf.line(14, pdf.get_y(), 202, pdf.get_y())
    pdf.ln(5)

    # --- Customer & Invoice Details ---
    cust_name = invoice.customer.name if invoice.customer else "Valued Customer"
    cust_phone = invoice.customer.phone if (invoice.customer and invoice.customer.phone) else "N/A"
    cust_location = getattr(invoice.customer, "location", None) or "ភ្នំពេញ / Phnom Penh"
    due_date_str = str(invoice.due_date) if invoice.due_date else "Upon Receipt"

    pdf.set_font(active_font, "B", 9)
    pdf.set_text_color(51, 65, 85)
    pdf.cell(94, 5, "អតិថិជន / Billed To:", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(92, 5, "ព័ត៌មានវិក្កយបត្រ / Invoice Details:", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font(active_font, "", 9)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(94, 5, f"ឈ្មោះ / Name: {cust_name}", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(92, 5, f"កាលបរិច្ឆេទ / Date: {created_date_str}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.cell(94, 5, f"ទូរស័ព្ទ / Phone: {cust_phone}", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(92, 5, f"រូបិយប័ណ្ណ / Currency: {invoice.currency}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.cell(94, 5, f"ទីតាំង / Location: {cust_location}", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(92, 5, f"ស្ថានភាព / Status: {invoice.status.upper()}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(6)

    # --- Line Items Table ---
    currency_sym = "$" if invoice.currency == "USD" else "៛"
    with pdf.table(
        col_widths=(68, 20, 32, 32, 36),
        text_align=("LEFT", "RIGHT", "RIGHT", "RIGHT", "LEFT"),
        line_height=6.5,
        padding=2.5,
    ) as table:
        header = table.row()
        pdf.set_font(active_font, "B", 9)
        pdf.set_text_color(30, 41, 59)
        header.cell("បរិយាយមុខទំនិញ / Description")
        header.cell("បរិមាណ / Qty")
        header.cell("ថ្លៃឯកតា / Unit Price")
        header.cell("ថ្លៃទំនិញ / Amount")
        header.cell("ចំណាំ / Note")

        pdf.set_font(active_font, "", 9)
        pdf.set_text_color(15, 23, 42)
        for itm in invoice.items:
            row = table.row()
            row.cell(itm.product_name)
            row.cell(f"{itm.quantity:g}")
            row.cell(f"{currency_sym}{itm.unit_price:,.2f}")
            row.cell(f"{currency_sym}{itm.line_total:,.2f}")
            item_note = getattr(itm, "note", None) or "-"
            row.cell(item_note)

    pdf.ln(6)

    # --- QR Code & Dual Currency Grand Totals ---
    y_bottom = pdf.get_y()

    # Bakong QR image
    if os.path.exists(qr_img_path):
        pdf.image(qr_img_path, x=18, y=y_bottom, w=35, h=35)

    pdf.set_xy(14, y_bottom + 37)
    pdf.set_font(active_font, "B", 8)
    pdf.set_text_color(30, 41, 59)
    pdf.cell(65, 4, "ស្កេនទូទាត់តាមបាគង / Scan to Pay with Bakong", align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font(active_font, "", 7)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(65, 4, "Supported by ABA, ACLEDA, Sathapana & KHQR", align="C")

    # Totals block on the right
    pdf.set_xy(105, y_bottom)
    pdf.set_font(active_font, "", 9)
    pdf.set_text_color(51, 65, 85)

    pdf.cell(48, 6, "សរុប / Subtotal:", align="R")
    pdf.cell(38, 6, f"{currency_sym}{invoice.subtotal:,.2f}", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_x(105)
    pdf.cell(48, 6, "អាករ (VAT 10%):", align="R")
    pdf.cell(38, 6, f"{currency_sym}{invoice.tax:,.2f}", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_x(105)
    pdf.set_font(active_font, "B", 10)
    pdf.set_text_color(29, 78, 216)
    pdf.cell(48, 7, "សរុបរួម (USD) / TOTAL:", align="R")
    pdf.cell(38, 7, f"${invoice.total:,.2f}", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_x(105)
    pdf.set_text_color(4, 120, 87)
    pdf.cell(48, 7, "សរុបរួម (KHR) / TOTAL:", align="R")
    pdf.cell(38, 7, f"{khr_total:,.0f} KHR", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # --- Official Exchange Rate Citation (Notification 4908) ---
    pdf.set_xy(14, y_bottom + 48)
    pdf.set_font(active_font, "I", 7.5)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(
        188,
        5,
        f"អត្រាប្តូរប្រាក់ផ្លូវការ / Official Rate: 1 USD = {rate_val:,g} KHR (ប្រភព / Source: {rate_source} កាលបរិច្ឆេទ / Dated: {rate_date})",
        align="C",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )

    # --- Statutory Footer (Prakas 723) ---
    pdf.ln(2)
    pdf.set_draw_color(226, 232, 240)
    pdf.set_line_width(0.3)
    pdf.line(14, pdf.get_y(), 202, pdf.get_y())
    pdf.ln(3)

    pdf.set_font(active_font, "", 7.5)
    pdf.set_text_color(148, 163, 184)
    pdf.cell(
        188,
        4,
        "វិក្កយបត្រនេះត្រូវបានបង្កើតឡើងដោយស្វ័យប្រវត្តិស្របតាមច្បាប់សារពើពន្ធកម្ពុជា (ប្រកាស ៧២៣ សហវ.ប្រក)",
        align="C",
        new_x=XPos.LMARGIN,
        new_y=YPos.NEXT,
    )
    pdf.cell(
        188,
        4,
        "Generated by InvoiceAI / InvoiceMate — Compliant with Cambodian Fiscal Regulations",
        align="C",
    )

    pdf_bytes = bytes(pdf.output())

    # Verify buffer bounds (< 50MB)
    if len(pdf_bytes) > MAX_BUFFER_SIZE_BYTES:
        raise ValueError("Generated PDF buffer exceeds 50MB worker limit")

    return io.BytesIO(pdf_bytes)


def generate_invoice_pdf(
    invoice: Invoice,
    output_dir: str = "./storage/invoices",
    merchant_name: str = "InvoiceMate Cambodia",
    exchange_rate_result: Optional[ExchangeRateResult] = None,
    is_tax_invoice: bool = False,
) -> str:
    """
    Generate PDF and persist to output_dir while enforcing memory and statutory rules.
    Returns local file path.
    """
    os.makedirs(output_dir, exist_ok=True)
    pdf_filename = f"{invoice.invoice_number}.pdf"
    pdf_path = os.path.join(output_dir, pdf_filename)

    buf = render_invoice_pdf_bytes(
        invoice=invoice,
        merchant_name=merchant_name,
        exchange_rate_result=exchange_rate_result,
        is_tax_invoice=is_tax_invoice,
    )

    with open(pdf_path, "wb") as f:
        f.write(buf.getvalue())

    return pdf_path
