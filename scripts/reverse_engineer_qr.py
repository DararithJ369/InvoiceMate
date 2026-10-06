import os
import json
import zxingcpp
from PIL import Image


def parse_emvco_khqr(payload: str) -> dict:
    idx = 0
    parsed = {}
    while idx < len(payload):
        if idx + 4 > len(payload):
            break
        tag = payload[idx : idx + 2]
        length_str = payload[idx + 2 : idx + 4]
        try:
            length = int(length_str)
        except ValueError:
            break

        val = payload[idx + 4 : idx + 4 + length]
        idx += 4 + length

        sub_parsed = None
        if tag in ["29", "30", "62"] and len(val) > 4:
            sub_idx = 0
            sub_parsed = {}
            while sub_idx < len(val):
                if sub_idx + 4 > len(val):
                    break
                stag = val[sub_idx : sub_idx + 2]
                slen_str = val[sub_idx + 2 : sub_idx + 4]
                try:
                    slen = int(slen_str)
                except ValueError:
                    break
                sval = val[sub_idx + 4 : sub_idx + 4 + slen]
                sub_idx += 4 + slen
                sub_parsed[stag] = sval

        parsed[tag] = {
            "length": length,
            "value": val,
            "sub_tags": sub_parsed,
        }

    return parsed


def crc16_ccitt(data: str) -> str:
    crc = 0xFFFF
    for char in data:
        crc ^= ord(char) << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def reverse_engineer(img_path: str):
    if not os.path.exists(img_path):
        print(f"Error: File {img_path} not found")
        return

    img = Image.open(img_path)
    results = zxingcpp.read_barcodes(img)

    if not results:
        print("Error: Could not decode barcode with zxingcpp")
        return

    for result in results:
        val = result.text
        print("=" * 60)
        print("RAW KHQR / EMVCo DECODED PAYLOAD:")
        print("=" * 60)
        print(val)
        print("=" * 60)
        print(f"Format: {result.format} | Payload Length: {len(val)} characters\n")

        # Validate CRC16
        payload_without_crc = val[:-4]
        expected_crc = val[-4:]
        calculated_crc = crc16_ccitt(payload_without_crc)
        crc_valid = (expected_crc.upper() == calculated_crc.upper())

        print("CRC16 CHECKSUM VERIFICATION:")
        print(f"  • Expected CRC in QR:   {expected_crc}")
        print(f"  • Calculated CRC-CCITT: {calculated_crc}")
        print(f"  • CRC Match Valid:      {'✅ YES (100% Valid EMVCo/KHQR Checksum)' if crc_valid else '❌ NO'}\n")

        # Parse EMVCo / KHQR tags
        parsed = parse_emvco_khqr(val)

        tag_descriptions = {
            "00": "Payload Format Indicator",
            "01": "Point of Initiation Method (11=Static, 12=Dynamic)",
            "29": "Merchant Account Information (Bakong ID / KHQR)",
            "30": "Merchant Account Information (Alternative)",
            "52": "Merchant Category Code (MCC)",
            "53": "Transaction Currency (840=USD, 116=KHR)",
            "54": "Transaction Amount",
            "58": "Country Code (KH=Cambodia)",
            "59": "Merchant Name",
            "60": "Merchant City",
            "62": "Additional Data Field Template (Bill / Ref #)",
            "63": "CRC16 Checksum",
        }

        subtag_descriptions = {
            "00": "Bakong Account ID / Merchant ID",
            "01": "Bill Number / Reference ID",
            "02": "Mobile Number / Bank Name",
        }

        print("TAG-BY-TAG EMVCo KHQR BREAKDOWN:")
        print("=" * 60)
        for tag, data in parsed.items():
            desc = tag_descriptions.get(tag, "Custom Tag")
            print(f"Tag [{tag}] -> {desc}:")
            print(f"  Length: {data['length']} bytes")
            print(f"  Raw Value: '{data['value']}'")
            if data["sub_tags"]:
                print("  Sub-fields:")
                for stag, sval in data["sub_tags"].items():
                    sdesc = subtag_descriptions.get(stag, "Sub-field")
                    print(f"    • Sub-Tag [{stag}] ({sdesc}): '{sval}'")
            print("-" * 60)


if __name__ == "__main__":
    import argparse
    import glob
    import sys

    parser = argparse.ArgumentParser(description="Reverse Engineer and Validate EMVCo KHQR Barcode Image")
    parser.add_argument("image", nargs="?", help="Path to QR code image (PNG/JPEG)")
    args = parser.parse_args()

    target = args.image
    if not target:
        candidates = (
            glob.glob("./storage/invoices/qr/*_qr.png")
            + glob.glob("./storage/*.png")
            + glob.glob("./storage/test_qr.png")
        )
        if candidates:
            target = candidates[0]
            print(f"No image path specified. Auto-detected QR asset: {target}\n")
        else:
            print("Usage: uv run python scripts/reverse_engineer_qr.py <path_to_qr_image.png>")
            sys.exit(1)

    reverse_engineer(target)
