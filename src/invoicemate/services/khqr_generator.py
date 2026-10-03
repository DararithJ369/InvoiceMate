import hashlib
import io
import os
import qrcode
from decimal import Decimal
from typing import Optional, Tuple

from invoicemate.core.config import settings


def _crc16_ccitt(data: str) -> str:
    """
    Calculate CRC16-CCITT checksum for KHQR / EMVCo QR code string.
    Polynomial: 0x1021, Initial: 0xFFFF.
    """
    crc = 0xFFFF
    for char in data:
        crc ^= ord(char) << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def generate_khqr_string(
    merchant_name: str = "InvoiceMate Merchant",
    bakong_account_id: Optional[str] = None,
    amount: Optional[Decimal] = None,
    currency: str = "USD",
    bill_number: Optional[str] = None,
) -> str:
    """
    Generate Bakong KHQR compliant EMVCo payload string for Cambodia payments.
    """
    account_id = bakong_account_id or settings.BAKONG_ACCOUNT_ID
    currency_code = "840" if currency.upper() == "USD" else "116"
    amount_str = f"{amount:.2f}" if amount else ""

    initiation_method = "12" if amount else "11"
    
    payload = "000201"
    payload += f"0102{initiation_method}"

    # Tag 29: Bakong Merchant Account Info
    merchant_info = f"00{len(account_id):02d}{account_id}"
    payload += f"29{len(merchant_info):02d}{merchant_info}"

    # Tag 52: Merchant Category Code (5999)
    payload += "52045999"

    # Tag 53: Transaction Currency (840 / 116)
    payload += f"5303{currency_code}"

    # Tag 54: Transaction Amount
    if amount_str:
        payload += f"54{len(amount_str):02d}{amount_str}"

    # Tag 58: Country Code (KH)
    payload += "5802KH"

    # Tag 59: Merchant Name
    clean_merchant = merchant_name[:25]
    payload += f"59{len(clean_merchant):02d}{clean_merchant}"

    # Tag 60: Merchant City (Phnom Penh)
    city = "Phnom Penh"
    payload += f"60{len(city):02d}{city}"

    # Tag 62: Additional Data Field Template (Bill Number)
    if bill_number:
        bill_tag = f"01{len(bill_number):02d}{bill_number}"
        payload += f"62{len(bill_tag):02d}{bill_tag}"

    # Tag 63: CRC16 Checksum prefix
    payload += "6304"

    checksum = _crc16_ccitt(payload)
    return payload + checksum


def calculate_khqr_md5(khqr_string: str) -> str:
    """
    Calculate MD5 hash of the KHQR string.
    Compliant with Bakong Open API payment settlement hash tracking.
    """
    return hashlib.md5(khqr_string.encode("utf-8")).hexdigest()


def generate_dynamic_khqr(
    merchant_name: str = "InvoiceMate Merchant",
    amount: Optional[Decimal] = None,
    currency: str = "USD",
    bill_number: Optional[str] = None,
    bakong_account_id: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Generate NBC-compliant Dynamic KHQR payload incorporating bakong_id, amount,
    currency (USD/KHR), merchant_name, and bill_number.
    Returns tuple: (khqr_string, khqr_md5)
    """
    khqr_str = generate_khqr_string(
        merchant_name=merchant_name,
        bakong_account_id=bakong_account_id,
        amount=amount,
        currency=currency,
        bill_number=bill_number,
    )
    khqr_md5 = calculate_khqr_md5(khqr_str)
    return khqr_str, khqr_md5


def generate_khqr_image(
    khqr_string: str, output_path: Optional[str] = None
) -> str:
    """
    Generate QR code image from KHQR payload string and save to output_path.
    Returns the file path.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(khqr_string)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#1a365d", back_color="white")

    if not output_path:
        os.makedirs("./storage/qr", exist_ok=True)
        output_path = f"./storage/qr/khqr_{hash(khqr_string) & 0xffffffff}.png"
    else:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

    img.save(output_path)
    return output_path
