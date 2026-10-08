"""OCR provider layer (Phase 3).

Turns uploaded KYC / invoice images and PDFs into plain text so a reviewer
gets read-only suggestions instead of retyping everything.

Design rules:
  * ``OCRProvider.extract_text()`` always returns an :class:`OCRResult` and
    NEVER raises — network problems, bad keys, malformed responses and
    provider errors come back as ``ok=False`` with a short, redacted error.
  * The API key is only ever placed in the request header, never in a log
    line, error message or stored field (``_redact()`` strips it too).
  * Work runs on a daemon thread started after the upload transaction
    commits (``process_document``), because Render's free tier has no
    worker process. The thread closes its DB connection when done.
  * Everything is off until ``OCR_ENABLED`` is turned on in the environment.
"""

import io
import json
import logging
import mimetypes
import os
import uuid
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache
from django.db import connections
from django.utils import timezone

logger = logging.getLogger('core.ocr')

OCRSPACE_ENDPOINT = 'https://api.ocr.space/parse/image'
DEFAULT_TIMEOUT = 25          # seconds per spec
MAX_TEXT = 20000              # characters of OCR text we keep per document
QUOTA_TTL = 60 * 60 * 24      # lifetime of the daily counter


@dataclass
class OCRResult:
    """Outcome of one OCR attempt (never a raised exception)."""

    ok: bool
    text: str = ''
    error: str = ''
    provider: str = ''

    def __str__(self):
        return f'{self.provider} ok={self.ok} text={len(self.text)} error={self.error}'


def _redact(text):
    """Strip the configured API key from a string before it is stored/logged."""
    text = str(text)
    key = getattr(settings, 'OCRSPACE_API_KEY', '')
    if key and key in text:
        text = text.replace(key, '[redacted]')
    return text


def _short(text, limit=200):
    return ' '.join(_redact(str(text)).split())[:limit]


class OCRProvider:
    """Interface every OCR backend implements."""

    name = 'base'

    def extract_text(self, file_bytes, filename, content_type=''):
        """Return an :class:`OCRResult`. Must never raise."""
        raise NotImplementedError


class OCRSpaceProvider(OCRProvider):
    """Text extraction through the OCR.space HTTP API.

    The request is hand-built multipart/form-data over urllib — the project
    takes no new dependencies. The API key travels in the ``apikey`` header
    and is never included in the request body, logs or errors.
    """

    name = 'ocrspace'

    def __init__(self, api_key='', timeout=DEFAULT_TIMEOUT):
        self.api_key = (api_key or '').strip()
        self.timeout = timeout

    def extract_text(self, file_bytes, filename, content_type=''):
        if not self.api_key:
            return OCRResult(False, '', 'OCR is not configured (missing API key)', self.name)

        filename = filename or 'upload'
        content_type = (
            content_type
            or mimetypes.guess_type(filename)[0]
            or 'application/octet-stream'
        )
        boundary = '----partnerportal' + uuid.uuid4().hex
        body = self._build_body(file_bytes, filename, content_type, boundary)

        request = Request(
            OCRSPACE_ENDPOINT,
            data=body,
            method='POST',
            headers={
                'apikey': self.api_key,
                'Content-Type': f'multipart/form-data; boundary={boundary}',
                'Accept': 'application/json',
                'User-Agent': 'partner-portal-ocr/1.0',
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = ''
            try:
                detail = exc.read(1024).decode('utf-8', 'replace')
            except Exception:  # noqa: BLE001 - body is best effort
                detail = ''
            return OCRResult(False, '', _short(f'ocr.space HTTP {exc.code}: {detail}'), self.name)
        except (URLError, TimeoutError, OSError) as exc:
            return OCRResult(False, '', _short(f'ocr.space request failed: {exc}'), self.name)
        except Exception as exc:  # noqa: BLE001 - a provider must never raise
            return OCRResult(False, '', _short(f'ocr.space request failed: {exc}'), self.name)

        return self._parse(raw)

    @staticmethod
    def _build_body(file_bytes, filename, content_type, boundary):
        """Hand-rolled multipart/form-data body (fields + one file part)."""
        parts = []

        def field(name, value):
            parts.append(f'--{boundary}\r\n'.encode())
            parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            parts.append(str(value).encode() + b'\r\n')

        field('language', 'eng')
        field('OCREngine', '2')
        field('isOverlayRequired', 'false')

        parts.append(f'--{boundary}\r\n'.encode())
        parts.append(
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode()
        )
        parts.append(f'Content-Type: {content_type}\r\n\r\n'.encode())
        parts.append(file_bytes)
        parts.append(b'\r\n')
        parts.append(f'--{boundary}--\r\n'.encode())
        return b''.join(parts)

    @staticmethod
    def _parse(raw):
        try:
            payload = json.loads(raw.decode('utf-8', 'replace'))
        except ValueError:
            return OCRResult(False, '', 'ocr.space returned a non-JSON response', 'ocrspace')

        if payload.get('IsErroredOnProcessing'):
            message = payload.get('ErrorMessage') or payload.get('ErrorDetails') or 'processing failed'
            if isinstance(message, (list, tuple)):
                message = '; '.join(str(item) for item in message)
            return OCRResult(False, '', _short(f'ocr.space: {message}'), 'ocrspace')

        results = payload.get('ParsedResults') or []
        chunks = []
        for item in results:
            if isinstance(item, dict) and item.get('ParsedText'):
                chunks.append(str(item['ParsedText']).strip())
        text = '\n'.join(chunk for chunk in chunks if chunk).strip()
        return OCRResult(True, text[:MAX_TEXT], '', 'ocrspace')


def get_provider():
    """Return the configured provider, or ``None`` when OCR is off."""
    if not getattr(settings, 'OCR_ENABLED', False):
        return None
    name = (getattr(settings, 'OCR_PROVIDER', 'ocrspace') or 'ocrspace').strip().lower()
    if name != 'ocrspace':
        logger.warning('unsupported OCR provider requested: %s', _redact(name))
        return None
    return OCRSpaceProvider(getattr(settings, 'OCRSPACE_API_KEY', ''))


def quota_available():
    """True while today's OCR call budget still has room."""
    limit = getattr(settings, 'OCR_DAILY_LIMIT', 100)
    if limit <= 0:
        return True
    return int(cache.get(_quota_key(), 0)) < limit


def bump_quota():
    key = _quota_key()
    cache.add(key, 0, QUOTA_TTL)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, QUOTA_TTL)


def _quota_key():
    return f'ocr:count:{timezone.localdate().isoformat()}'


def _downscale_image(file_bytes, filename, content_type):
    """Shrink an oversized image so it fits ``OCR_MAX_BYTES``.

    Returns ``(bytes, filename, content_type)`` or ``None`` when the file
    cannot be shrunk (Pillow missing, not an image, or corrupt data).
    Pillow is an optional import so the portal still runs without it.
    """
    # Trust the stored MIME type, but fall back to the filename extension —
    # some clients upload images with a generic content type.
    guessed = mimetypes.guess_type(filename or '')[0] or ''
    if not (content_type or '').startswith('image/') and not guessed.startswith('image/'):
        return None
    try:
        from PIL import Image  # optional dependency
    except ImportError:
        return None
    try:
        image = Image.open(io.BytesIO(file_bytes))
        image = image.convert('RGB')
        image.thumbnail((1600, 1600))          # max side 1600 px
        buffer = io.BytesIO()
        image.save(buffer, format='JPEG', quality=80)
        stem = os.path.splitext(filename or 'image')[0] or 'image'
        return buffer.getvalue(), f'{stem}.jpg', 'image/jpeg'
    except Exception:  # noqa: BLE001 - any decode failure means "cannot shrink"
        return None


def process_document(document_pk):
    """Run OCR for one ``PartnerDocument``. Safe to call from a daemon thread.

    Sets ``ocr_status`` to done / failed / skipped, stores the masked text
    and the suggestion dict, and always closes the DB connection afterwards.
    Never raises.
    """
    from core.services.extraction import extract_suggestions, mask_aadhaar
    from partners.models import PartnerDocument

    document = None
    try:
        document = PartnerDocument.objects.filter(pk=document_pk).first()
        if document is None:
            return

        provider = get_provider()
        if provider is None:
            reason = 'OCR is not enabled' if not getattr(settings, 'OCR_ENABLED', False) else 'OCR is not configured'
            _finish(document, 'skipped', reason)
            return
        if not quota_available():
            _finish(document, 'skipped', 'daily OCR limit reached')
            return
        if not document.file:
            _finish(document, 'failed', 'no file to scan')
            return

        with document.file.open('rb') as handle:
            file_bytes = handle.read()

        filename = os.path.basename(document.file.name)
        content_type = ''
        getter = getattr(document.file.storage, 'get_content_type', None)
        if callable(getter):
            try:
                content_type = getter(document.file.name) or ''
            except Exception:  # noqa: BLE001 - stored MIME type is optional
                content_type = ''
        content_type = content_type or mimetypes.guess_type(filename)[0] or ''

        payload, payload_name, payload_type = file_bytes, filename, content_type
        max_bytes = getattr(settings, 'OCR_MAX_BYTES', 1048576)
        if len(file_bytes) > max_bytes:
            shrunk = _downscale_image(file_bytes, filename, content_type)
            if shrunk is None:
                _finish(document, 'skipped', 'file larger than 1 MB, enter details manually')
                return
            payload, payload_name, payload_type = shrunk

        document.ocr_status = 'processing'
        document.save(update_fields=['ocr_status'])

        result = provider.extract_text(payload, payload_name, payload_type)
        bump_quota()
        if not result.ok:
            _finish(document, 'failed', result.error or 'OCR failed')
            return

        text = mask_aadhaar(result.text)
        document.ocr_text = text
        document.extracted = extract_suggestions(text, document.doc_type)
        document.ocr_error = ''
        document.ocr_status = 'done'
        document.save(update_fields=['ocr_status', 'ocr_text', 'extracted', 'ocr_error'])
        logger.info('OCR done for document %s (%s chars)', document.pk, len(text))
    except Exception as exc:  # noqa: BLE001 - a background worker must never raise
        logger.exception('OCR run for document %s failed: %s', document_pk, _short(exc))
        if document is not None:
            _finish(document, 'failed', _short(exc))
    finally:
        try:
            connections['default'].close()
        except Exception:  # noqa: BLE001 - closing is best effort
            pass


def _finish(document, status, error=''):
    """Persist a terminal OCR state. Never raises."""
    try:
        document.ocr_status = status
        document.ocr_error = _short(error)
        document.save(update_fields=['ocr_status', 'ocr_error'])
        logger.info('OCR for document %s -> %s (%s)', document.pk, status, document.ocr_error or 'ok')
    except Exception:  # noqa: BLE001 - even the failure path must be quiet
        logger.exception('could not record OCR state for document %s', document.pk)
