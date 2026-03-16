from firebase_admin import storage
from config import Config
import uuid
import os
import logging

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
            method='GET'
        )
        return url
