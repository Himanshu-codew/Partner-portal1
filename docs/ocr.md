# OCR for KYC and invoice documents

Partners upload KYC / invoice files (PDF, JPG, PNG — max 5 MB) from
**My KYC** in the sidebar. The portal extracts the text in the background,
masks Aadhaar numbers, and shows a reviewer read-only *suggestions* —
nothing is ever written back into a business record automatically.

## How it works

1. **Upload** — the partner picks a document type (PAN, GST, BANK,
   INVOICE, OTHER) and a file. Bytes are stored in the database
   (`core.StoredFile` via `DatabaseFileStorage`), so they survive Render
   redeploys.
2. **Background run** — after the upload transaction commits, a daemon
   thread (`core.services.ocr.process_document`) runs the OCR provider.
   Render's free tier has no worker process, hence the thread; the job
   never raises and closes its DB connection when finished.
3. **Provider call** — `OCRSpaceProvider` POSTs hand-built
   `multipart/form-data` to `https://api.ocr.space/parse/image` with the
   key in the `apikey` header (25 s timeout). All errors are caught and
   returned as a failed result — the key is never logged or stored.
4. **Masking + suggestions** — the text is passed through
   `mask_aadhaar()` (`XXXX XXXX 1234`, last four kept) *before* it is
   saved, then `extract_suggestions()` scans the masked text for PAN,
   GSTIN, IFSC, account numbers (BANK only), invoice numbers, totals,
   emails and mobiles.
5. **Review** — a staff member opens **KYC Documents**, previews the
   file, reads the masked OCR text and suggestions, and approves or
   rejects with an optional note (POST-only). The partner is notified by
   email/WhatsApp (`kyc_reviewed` event).

The OCR status of a document is `pending → processing → done / failed /
skipped`. **Retry OCR** (POST) re-runs any non-processing document.

## Environment variables (Render)

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `OCR_ENABLED` | yes (to run) | `False` | Master switch. Off = uploads are marked `skipped` ("OCR is not enabled") and no HTTP call is made. |
| `OCRSPACE_API_KEY` | yes | – | OCR.space API key (header only, redacted everywhere). |
| `OCR_PROVIDER` | no | `ocrspace` | Only `ocrspace` is implemented. |
| `OCR_DAILY_LIMIT` | no | `100` | Max provider calls per day (`<= 0` = unlimited). Over the limit = `skipped`. |
| `OCR_MAX_BYTES` | no | `1048576` | Larger *images* are downscaled to ≤1600 px / JPEG 80 (Pillow) when available; otherwise they are `skipped` with "file larger than 1 MB, enter details manually". |

## OCR.space free limits

- **25,000** requests per month, **500** per day per IP address.
- Max file size **1 MB**, max **3 pages** for PDFs.
- Free tier requires a visible attribution/credit on the page when used
  in production — check their current terms.

## Privacy warning (read this before enabling)

OCR.space processes the file **on a third-party server**: the uploaded
document leaves the machine and is seen by the provider. Aadhaar numbers
are masked *after* the provider has already seen the raw image. Only use
**test documents** until the client has explicitly approved a provider
(and a data-processing agreement) for real KYC data. Never enable OCR in
production with real PAN/Aadhaar/invoice documents on a free tier.

## Switching providers

Implement a subclass of `OCRProvider`:

```python
class MyProvider(OCRProvider):
    name = 'myprovider'

    def extract_text(self, file_bytes, filename, content_type=''):
        # must NEVER raise; return OCRResult(ok, text, error)
        ...
```

…and return it from `get_provider()` in `core/services/ocr.py` when
`OCR_PROVIDER` matches. Everything else (threading, quota, masking,
suggestions, retry, review UI) stays unchanged.
