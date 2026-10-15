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

Providers (``OCR_PROVIDER``):
  * ``ocrspace`` (default) — the OCR.space HTTP API. Metered: counts against
    ``OCR_DAILY_LIMIT`` and is limited to ``OCR_MAX_BYTES`` per file.
  * ``tesseract`` — the Tesseract engine installed on the same server (see
    the Dockerfile). No API key, no daily limit, files never leave the
    server. PDFs are rendered to images with poppler's ``pdftoppm``.
  * ``hybrid`` — Tesseract first; OCR.space only when Tesseract finds little
    or no text and the daily quota still has room.
  * ``remote`` — Tesseract on a separate OCR helper service (the Docker
    image with ``OCR_WORKER_ONLY``), reached over HTTPS at ``OCR_REMOTE_URL``
    with the shared ``OCR_WORKER_TOKEN``. Lets the main portal stay on the
    native Python runtime. ``remote_hybrid`` adds the OCR.space fallback.
"""

import glob
import io
import json
import logging
import mimetypes
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import connections
from django.utils import timezone

logger = logging.getLogger('core.ocr')

OCRSPACE_ENDPOINT = 'https://api.ocr.space/parse/image'
DEFAULT_TIMEOUT = 25          # seconds per spec
MAX_TEXT = 20000              # characters of OCR text we keep per document
QUOTA_TTL = 60 * 60 * 24      # lifetime of the daily counter
METERED_PROVIDERS = {'ocrspace'}  # providers that consume OCR_DAILY_LIMIT
HYBRID_MIN_CHARS = 20         # less local text than this triggers the fallback
LOCAL_MAX_SIDE = 2500         # px; larger images are shrunk before Tesseract
PDF_RENDER_DPI = 200

# Tesseract needs ~100-200 MB per run; Render's free plan has 512 MB, so only
# one local OCR job runs at a time. Others wait their turn on this lock.
_local_ocr_lock = threading.Lock()


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
    """Strip the API key and helper token from a string before it is stored/logged."""
    text = str(text)
    for secret in (
        getattr(settings, 'OCRSPACE_API_KEY', ''),
        getattr(settings, 'OCR_WORKER_TOKEN', ''),
    ):
        if secret and secret in text:
            text = text.replace(secret, '[redacted]')
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


class TesseractProvider(OCRProvider):
    """Text extraction with the Tesseract binary on this server.

    Runs ``tesseract`` (and ``pdftoppm`` for PDFs) as subprocesses with a
    timeout, inside a temporary directory that is always removed. Only one
    job runs at a time (``_local_ocr_lock``) to stay within free-tier memory.
    Never raises: a missing binary, timeout or bad file is a failed result.
    """

    name = 'tesseract'

    def __init__(self, lang='eng+hin', timeout=120, max_pages=5):
        self.lang = (lang or 'eng').strip()
        self.timeout = timeout
        self.max_pages = max(1, int(max_pages or 1))

    def extract_text(self, file_bytes, filename, content_type=''):
        try:
            if not shutil.which('tesseract'):
                return OCRResult(False, '', 'Tesseract is not installed on this server', self.name)
            with _local_ocr_lock, tempfile.TemporaryDirectory(prefix='ocr-') as workdir:
                if self._is_pdf(file_bytes, filename, content_type):
                    pages = self._render_pdf(file_bytes, workdir)
                    if isinstance(pages, OCRResult):
                        return pages
                else:
                    pages = [self._write_image(file_bytes, filename, workdir)]

                chunks = []
                for page in pages:
                    result = self._run(['tesseract', page, 'stdout', '-l', self.lang])
                    if isinstance(result, OCRResult):
                        return result
                    if result.strip():
                        chunks.append(result.strip())
            text = '\n'.join(chunks).strip()
            return OCRResult(True, text[:MAX_TEXT], '', self.name)
        except Exception as exc:  # noqa: BLE001 - a provider must never raise
            return OCRResult(False, '', _short(f'tesseract failed: {exc}'), self.name)

    @staticmethod
    def _is_pdf(file_bytes, filename, content_type):
        return (
            (content_type or '').lower() == 'application/pdf'
            or (filename or '').lower().endswith('.pdf')
            or file_bytes[:5] == b'%PDF-'
        )

    def _render_pdf(self, file_bytes, workdir):
        """Render up to ``max_pages`` PDF pages to PNG files in ``workdir``."""
        if not shutil.which('pdftoppm'):
            return OCRResult(False, '', 'pdftoppm (poppler) is not installed on this server', self.name)
        source = os.path.join(workdir, 'input.pdf')
        with open(source, 'wb') as handle:
            handle.write(file_bytes)
        result = self._run([
            'pdftoppm', '-r', str(PDF_RENDER_DPI), '-png',
            '-f', '1', '-l', str(self.max_pages),
            source, os.path.join(workdir, 'page'),
        ])
        if isinstance(result, OCRResult):
            return result
        pages = sorted(glob.glob(os.path.join(workdir, 'page*.png')))
        if not pages:
            return OCRResult(False, '', 'PDF has no readable pages', self.name)
        return pages

    @staticmethod
    def _write_image(file_bytes, filename, workdir):
        """Save the image for Tesseract, shrinking huge photos when Pillow is available."""
        extension = os.path.splitext(filename or '')[1].lower() or '.png'
        path = os.path.join(workdir, 'input' + extension)
        try:
            from PIL import Image  # optional dependency
            image = Image.open(io.BytesIO(file_bytes))
            if max(image.size) > LOCAL_MAX_SIDE:
                image = image.convert('RGB')
                image.thumbnail((LOCAL_MAX_SIDE, LOCAL_MAX_SIDE))
                path = os.path.join(workdir, 'input.png')
                image.save(path, format='PNG')
                return path
        except Exception:  # noqa: BLE001 - Pillow missing or unreadable: use the bytes as-is
            pass
        with open(path, 'wb') as handle:
            handle.write(file_bytes)
        return path

    def _run(self, command):
        """Run one subprocess; return its stdout, or a failed OCRResult."""
        tool = command[0]
        env = dict(os.environ, OMP_THREAD_LIMIT='1')  # keep CPU/memory use low
        try:
            completed = subprocess.run(
                command, capture_output=True, timeout=self.timeout, env=env, check=False,
            )
        except subprocess.TimeoutExpired:
            return OCRResult(False, '', f'{tool} timed out after {self.timeout}s', self.name)
        except OSError as exc:
            return OCRResult(False, '', _short(f'{tool} could not start: {exc}'), self.name)
        if completed.returncode != 0:
            detail = completed.stderr.decode('utf-8', 'replace') if completed.stderr else ''
            return OCRResult(False, '', _short(f'{tool} failed: {detail}'), self.name)
        return completed.stdout.decode('utf-8', 'replace') if completed.stdout else ''


class HybridProvider(OCRProvider):
    """Tesseract first; OCR.space only as a fallback while quota remains.

    The fallback runs when Tesseract fails or returns fewer than
    ``HYBRID_MIN_CHARS`` characters, OCR.space has an API key, the daily
    quota has room and the file fits (or can be shrunk to) ``OCR_MAX_BYTES``.
    Otherwise the Tesseract result is returned as it is.
    """

    name = 'hybrid'

    def __init__(self, local, remote):
        self.local = local
        self.remote = remote

    def extract_text(self, file_bytes, filename, content_type=''):
        result = self.local.extract_text(file_bytes, filename, content_type)
        if result.ok and len(result.text.strip()) >= HYBRID_MIN_CHARS:
            return result
        if not self.remote.api_key or not quota_available():
            return result

        payload = _fit_to_size(
            file_bytes, filename, content_type, getattr(settings, 'OCR_MAX_BYTES', 1048576)
        )
        if payload is None:
            return result
        fallback = self.remote.extract_text(*payload)
        bump_quota()
        if fallback.ok and len(fallback.text.strip()) >= len(result.text.strip()):
            return fallback
        if result.ok:
            return result
        return OCRResult(False, '', f'{result.error}; fallback: {fallback.error}', self.name)


class RemoteOCRProvider(OCRProvider):
    """Tesseract on the separate OCR helper service, over HTTPS.

    POSTs the file to ``<OCR_REMOTE_URL>/internal/ocr/`` with the shared
    ``OCR_WORKER_TOKEN`` as a Bearer token. A free Render helper sleeps when
    idle and can answer 502/503 or drop the connection while it wakes up, so
    one retry follows a short pause. Never raises; the token is never logged.
    """

    name = 'remote'
    RETRY_DELAY = 10  # seconds between the two attempts

    def __init__(self, url='', token='', timeout=300):
        self.url = (url or '').strip().rstrip('/')
        self.token = (token or '').strip()
        self.timeout = timeout

    def extract_text(self, file_bytes, filename, content_type=''):
        if not self.url or not self.token:
            return OCRResult(
                False, '', 'OCR helper is not configured (OCR_REMOTE_URL / OCR_WORKER_TOKEN)', self.name
            )
        try:
            response = self._post(file_bytes, filename, content_type)
            if isinstance(response, OCRResult):
                return response
            if response.status_code != 200:
                return OCRResult(
                    False, '', _short(f'OCR helper HTTP {response.status_code}: {response.text[:200]}'), self.name
                )
            try:
                payload = response.json()
            except ValueError:
                return OCRResult(False, '', 'OCR helper returned a non-JSON response', self.name)
            if not isinstance(payload, dict):
                return OCRResult(False, '', 'OCR helper returned an unexpected response', self.name)
            text = str(payload.get('text') or '')
            return OCRResult(bool(payload.get('ok')), text[:MAX_TEXT], _short(payload.get('error') or ''), self.name)
        except Exception as exc:  # noqa: BLE001 - a provider must never raise
            return OCRResult(False, '', _short(f'OCR helper request failed: {exc}'), self.name)

    def _post(self, file_bytes, filename, content_type):
        """POST with one retry while the helper wakes up; a response or a failed OCRResult."""
        endpoint = f'{self.url}/internal/ocr/'
        for attempt in (1, 2):
            try:
                response = requests.post(
                    endpoint,
                    files={'file': (filename or 'upload', file_bytes, content_type or 'application/octet-stream')},
                    headers={'Authorization': f'Bearer {self.token}'},
                    timeout=(15, self.timeout),
                )
            except requests.RequestException as exc:
                if attempt == 1:
                    time.sleep(self.RETRY_DELAY)
                    continue
                return OCRResult(False, '', _short(f'OCR helper request failed: {type(exc).__name__}'), self.name)
            if response.status_code in (502, 503, 504) and attempt == 1:
                time.sleep(self.RETRY_DELAY)
                continue
            return response


def local_provider():
    """The Tesseract provider built from settings (also used by the helper endpoint)."""
    return TesseractProvider(
        lang=getattr(settings, 'OCR_TESSERACT_LANG', 'eng+hin'),
        timeout=getattr(settings, 'OCR_TESSERACT_TIMEOUT', 120),
        max_pages=getattr(settings, 'OCR_PDF_MAX_PAGES', 5),
    )


def remote_provider():
    return RemoteOCRProvider(
        url=getattr(settings, 'OCR_REMOTE_URL', ''),
        token=getattr(settings, 'OCR_WORKER_TOKEN', ''),
        timeout=getattr(settings, 'OCR_REMOTE_TIMEOUT', 300),
    )


def get_provider():
    """Return the configured provider, or ``None`` when OCR is off."""
    if not getattr(settings, 'OCR_ENABLED', False):
        return None
    name = (getattr(settings, 'OCR_PROVIDER', 'ocrspace') or 'ocrspace').strip().lower()
    ocrspace = OCRSpaceProvider(getattr(settings, 'OCRSPACE_API_KEY', ''))
    if name == 'ocrspace':
        return ocrspace
    if name == 'tesseract':
        return local_provider()
    if name == 'hybrid':
        return HybridProvider(local_provider(), ocrspace)
    if name == 'remote':
        return remote_provider()
    if name == 'remote_hybrid':
        return HybridProvider(remote_provider(), ocrspace)
    logger.warning('unsupported OCR provider requested: %s', _redact(name))
    return None


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


def _fit_to_size(file_bytes, filename, content_type, max_bytes):
    """Return ``(bytes, filename, content_type)`` within ``max_bytes``, or ``None``."""
    if len(file_bytes) <= max_bytes:
        return file_bytes, filename, content_type
    return _downscale_image(file_bytes, filename, content_type)


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
        metered = provider.name in METERED_PROVIDERS
        if metered and not quota_available():
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

        payload = (file_bytes, filename, content_type)
        if metered:
            # Local providers read the whole upload; the hosted API has a size cap.
            payload = _fit_to_size(*payload, getattr(settings, 'OCR_MAX_BYTES', 1048576))
            if payload is None:
                _finish(document, 'skipped', 'file larger than 1 MB, enter details manually')
                return

        document.ocr_status = 'processing'
        document.save(update_fields=['ocr_status'])

        result = provider.extract_text(*payload)
        if metered:
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
