from firebase_admin import storage
from config import Config
import uuid
import os

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

    @classmethod
    def upload_file(cls, file, folder='uploads'):
        """Upload a file to Firebase Storage

        Args:
            file: werkzeug FileStorage object
            folder: subfolder in the bucket

        Returns:
            dict with file_name, file_path, public_url, content_type, size
        """
        bucket = cls.get_bucket()

        # Generate unique filename
        ext = os.path.splitext(file.filename)[1]
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
