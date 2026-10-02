import os
import secrets
import shutil
from typing import Optional
from invoicemate.core.config import settings


def generate_secure_storage_token() -> str:
    """Generate a cryptographically secure random token for unguessable PDF URLs."""
    return secrets.token_urlsafe(16)


def store_invoice_pdf(
    source_pdf_path: str,
    token: Optional[str] = None,
    output_base_dir: Optional[str] = None,
) -> tuple[str, str]:
    """
    Store invoice PDF file under an unguessable directory token.
    Returns (destination_file_path, public_url).
    
    In dev: writes to storage/invoices/{token}/{filename}
    In prod: if R2 credentials exist, uploads to Cloudflare R2 bucket.
    """
    token_str = token or generate_secure_storage_token()
    base_dir = output_base_dir or settings.STORAGE_DIR
    filename = os.path.basename(source_pdf_path)

    # Secure directory structure
    token_dir = os.path.join(base_dir, token_str)
    os.makedirs(token_dir, exist_ok=True)
    destination_path = os.path.join(token_dir, filename)

    if os.path.abspath(source_pdf_path) != os.path.abspath(destination_path):
        shutil.copy2(source_pdf_path, destination_path)

    # Check Cloudflare R2 environment variables
    r2_bucket = os.getenv("R2_BUCKET_NAME")
    r2_public_url = os.getenv("R2_PUBLIC_BASE_URL")
    if r2_bucket and r2_public_url:
        try:
            # Upload to Cloudflare R2 using boto3/s3 client if configured
            import boto3
            s3 = boto3.client(
                "s3",
                endpoint_url=f"https://{os.getenv('R2_ACCOUNT_ID')}.r2.cloudflarestorage.com",
                aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
                aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
            )
            object_key = f"pdf/{token_str}/{filename}"
            with open(destination_path, "rb") as f:
                s3.upload_fileobj(f, r2_bucket, object_key, ExtraArgs={"ContentType": "application/pdf"})
            return destination_path, f"{r2_public_url.rstrip('/')}/pdf/{token_str}/{filename}"
        except Exception:
            pass  # Fall back to local hosted endpoint

    public_url = f"{settings.BASE_URL}/pdf/{token_str}/{filename}"
    return destination_path, public_url


def get_public_pdf_url(local_path_or_filename: str) -> str:
    """
    Convert a local PDF file path or filename to a public hosted HTTP URL.
    Supports secure token paths or standard paths.
    """
    if not local_path_or_filename:
        return ""

    if local_path_or_filename.startswith("http://") or local_path_or_filename.startswith("https://"):
        return local_path_or_filename

    parts = local_path_or_filename.replace("\\", "/").split("/")
    if len(parts) >= 2 and parts[-2] not in ["invoices", "storage", "."]:
        # Likely token/filename
        token = parts[-2]
        filename = parts[-1]
        return f"{settings.BASE_URL}/pdf/{token}/{filename}"

    filename = os.path.basename(local_path_or_filename)
    return f"{settings.BASE_URL}/invoices/{filename}"
