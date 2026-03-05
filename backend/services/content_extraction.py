import io
import csv
from services.storage_service import StorageService


class ContentExtraction:
    """Extract text from uploaded files for RAG indexing"""

    @classmethod
    def extract_from_storage(cls, file_path, file_type):
        """Download a file from Firebase Storage and extract text.

        Args:
            file_path: Path in Firebase Storage (e.g. 'content/abc123.pdf')
            file_type: Content type string ('PDF', 'CSV', 'Excel', 'Text', 'Document')

        Returns:
            str: Extracted text, or empty string on failure
        """
        try:
            bucket = StorageService.get_bucket()
            blob = bucket.blob(file_path)
            file_bytes = blob.download_as_bytes()

            file_type_upper = (file_type or '').upper()

            if file_type_upper == 'PDF':
                return cls._extract_pdf(file_bytes)
            elif file_type_upper == 'CSV':
                return cls._extract_csv(file_bytes)
            elif file_type_upper == 'EXCEL':
                return cls._extract_excel(file_bytes)
            else:
                # Try to read as plain text
                return cls._extract_text(file_bytes)
        except Exception as e:
            print(f"⚠️ Content extraction error for {file_path}: {e}")
            return ''

    @classmethod
    def _extract_pdf(cls, file_bytes):
        """Extract text from PDF bytes"""
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(io.BytesIO(file_bytes))
            pages = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
            return '\n\n'.join(pages)
        except Exception as e:
            print(f"⚠️ PDF extraction failed: {e}")
            return ''

    @classmethod
    def _extract_csv(cls, file_bytes):
        """Extract text from CSV bytes"""
        try:
            text = file_bytes.decode('utf-8', errors='replace')
            reader = csv.reader(io.StringIO(text))
            rows = []
            for i, row in enumerate(reader):
                rows.append(', '.join(row))
                if i > 500:  # Limit to 500 rows
                    rows.append('... (truncated)')
                    break
            return '\n'.join(rows)
        except Exception as e:
            print(f"⚠️ CSV extraction failed: {e}")
            return ''

    @classmethod
    def _extract_excel(cls, file_bytes):
        """Extract text from Excel bytes"""
        try:
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
            sheets = []
            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                rows = []
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    cells = [str(c) if c is not None else '' for c in row]
                    rows.append(', '.join(cells))
                    if i > 500:
                        rows.append('... (truncated)')
                        break
                sheets.append(f"[Sheet: {sheet_name}]\n" + '\n'.join(rows))
            wb.close()
            return '\n\n'.join(sheets)
        except Exception as e:
            print(f"⚠️ Excel extraction failed: {e}")
            return ''

    @classmethod
    def _extract_text(cls, file_bytes):
        """Try to read bytes as plain text"""
        try:
            return file_bytes.decode('utf-8', errors='replace')[:50000]
        except Exception:
            return ''
