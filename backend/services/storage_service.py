from firebase_admin import storage
from config import Config
import uuid
import os
import logging
import google.auth
from google.auth import impersonated_credentials
from google.auth.credentials import Signing as _SigningCredentials
from google.auth.transport.requests import Request as _GoogleAuthRequest

logger = logging.getLogger(__name__)

# Map extensions to expected MIME type prefixes for content-type validation
_EXTENSION_MIME_MAP = {
    '.jpg': 'image/', '.jpeg': 'image/', '.png': 'image/', '.gif': 'image/',
    '.webp': 'image/', '.svg': 'image/',
    '.pdf': 'application/pdf', '.doc': 'application/', '.docx': 'application/',
    '.xls': 'application/', '.xlsx': 'application/', '.csv': ('text/csv', 'application/'),
    '.mp4': 'video/', '.mov': 'video/',
}

class StorageService:
    """Service for Firebase Cloud Storage operations"""

    _bucket = None
    _signing_credentials = None

    @classmethod
    def get_bucket(cls):
        """Get the Firebase Storage bucket"""
        if cls._bucket is None:
            bucket_name = getattr(Config, 'FIREBASE_STORAGE_BUCKET', None)
            if not bucket_name:
                # Default Firebase storage bucket format
                project_id = Config.FIREBASE_PROJECT_ID or 'teko-236ad'
                bucket_name = f"{project_id}.firebasestorage.app"
            cls._bucket = storage.bucket(bucket_name)
        return cls._bucket

    @classmethod
    def get_signing_credentials(cls):
        """Credentials that can actually sign a URL (i.e. carry a private
        key), for use with blob.generate_signed_url(credentials=...).

        On Cloud Run/GCE, google.auth.default() returns
        google.auth.compute_engine.credentials.Credentials, which only ever
        carries a bearer token -- generate_signed_url() raises
        AttributeError on these no matter what IAM roles are granted,
        because nothing tells the library to sign via IAM instead of a
        local private key. The fix is to wrap the default credentials in
        impersonated_credentials.Credentials, targeting the SAME service
        account (self-impersonation): this routes signing through the IAM
        signBlob API, using the roles/iam.serviceAccountTokenCreator grant
        already present on this service account.

        A local service-account key file (google.oauth2.service_account.
        Credentials, e.g. via FIREBASE_CREDENTIALS_PATH) already implements
        google.auth.credentials.Signing directly -- no impersonation is
        needed or attempted for those, so local dev with a key file is
        unaffected.

        Cached at class level: building the impersonated credentials
        requires resolving the real service account email, which for
        compute engine credentials means a metadata-server round trip on
        first refresh -- this must not happen on every signed-URL call.
        """
        if cls._signing_credentials is None:
            credentials, _project = google.auth.default()
            if isinstance(credentials, _SigningCredentials):
                # Already has a private key -- use as-is, no impersonation.
                cls._signing_credentials = credentials
            else:
                if not credentials.valid:
                    # Also resolves compute-engine credentials' service
                    # account email from 'default' to the real address.
                    credentials.refresh(_GoogleAuthRequest())
                cls._signing_credentials = impersonated_credentials.Credentials(
                    source_credentials=credentials,
                    target_principal=credentials.service_account_email,
                    target_scopes=['https://www.googleapis.com/auth/cloud-platform'],
                    lifetime=3600,
                )
        return cls._signing_credentials

    # 10 MB max upload size
    MAX_FILE_SIZE = 10 * 1024 * 1024
    ALLOWED_EXTENSIONS = {
        '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg',  # images
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv',  # documents
        '.mp4', '.mov',  # video
    }

    @classmethod
    def upload_file(cls, file, folder='uploads'):
        """Upload a file to Firebase Storage

        Args:
            file: werkzeug FileStorage object
            folder: subfolder in the bucket

        Returns:
            dict with file_name, file_path, public_url, content_type, size

        Raises:
            ValueError: if file exceeds size limit or has disallowed extension
        """
        if not file or not hasattr(file, 'filename') or not file.filename:
            raise ValueError("No file provided")

        # Prevent path traversal in folder parameter
        folder = folder.strip()
        if '..' in folder or folder.startswith('/') or folder.startswith('\\'):
            raise ValueError("Invalid folder path")

        bucket = cls.get_bucket()

        # Validate extension
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in cls.ALLOWED_EXTENSIONS:
            raise ValueError(f"File type '{ext}' not allowed. Allowed: {', '.join(sorted(cls.ALLOWED_EXTENSIONS))}")

        # Validate content-type matches extension (prevent disguised uploads)
        content_type = (file.content_type or '').lower()
        expected = _EXTENSION_MIME_MAP.get(ext)
        if expected and content_type:
            prefixes = expected if isinstance(expected, tuple) else (expected,)
            if not any(content_type.startswith(p) for p in prefixes):
                logger.warning(f"Content-type mismatch: {file.filename} has type '{content_type}' but expected '{expected}'")
                raise ValueError(f"File content type '{content_type}' does not match extension '{ext}'")

        # Validate file size (read position, check, reset)
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        if size > cls.MAX_FILE_SIZE:
            raise ValueError(f"File too large ({size / 1024 / 1024:.1f} MB). Maximum is {cls.MAX_FILE_SIZE / 1024 / 1024:.0f} MB.")

        # Generate unique filename
        unique_name = f"{uuid.uuid4().hex}{ext}"
        blob_path = f"{folder}/{unique_name}"

        blob = bucket.blob(blob_path)
        blob.upload_from_file(file, content_type=file.content_type)

        # Make publicly accessible
        blob.make_public()

        return {
            'file_name': file.filename,
            'file_path': blob_path,
            'public_url': blob.public_url,
            'content_type': file.content_type,
            'size': blob.size
        }

    @classmethod
    def delete_file(cls, file_path):
        """Delete a file from Firebase Storage"""
        bucket = cls.get_bucket()
        blob = bucket.blob(file_path)
        blob.delete()
        return True

    @classmethod
    def get_signed_url(cls, file_path, expiration_minutes=60):
        """Get a temporary signed URL for a file"""
        from datetime import timedelta
        bucket = cls.get_bucket()
        blob = bucket.blob(file_path)
        url = blob.generate_signed_url(
            expiration=timedelta(minutes=expiration_minutes),
            method='GET',
            credentials=cls.get_signing_credentials(),
        )
        return url
