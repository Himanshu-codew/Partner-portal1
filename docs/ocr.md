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
3. **Provider call** — depends on `OCR_PROVIDER`:
   - `ocrspace` (default): `OCRSpaceProvider` POSTs hand-built
     `multipart/form-data` to `https://api.ocr.space/parse/image` with the
     key in the `apikey` header (25 s timeout).
   - `tesseract`: `TesseractProvider` runs the `tesseract` binary on the
     server (PDF pages are first rendered with `pdftoppm`). One job at a
     time, temporary files always removed.
   - `hybrid`: Tesseract first; OCR.space only when Tesseract fails or
     finds fewer than 20 characters and the daily quota has room.

   All errors are caught and returned as a failed result — the key is
   never logged or stored.
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
| `OCR_PROVIDER` | no | `ocrspace` | `ocrspace`, `tesseract` or `hybrid` (see below). |
| `OCRSPACE_API_KEY` | for `ocrspace` | – | OCR.space API key (header only, redacted everywhere). Optional with `hybrid` (no key = no fallback). |
| `OCR_DAILY_LIMIT` | no | `100` | Max **OCR.space** calls per day (`<= 0` = unlimited). Over the limit = `skipped` (`ocrspace`) or no fallback (`hybrid`). Tesseract runs are never counted. |
| `OCR_MAX_BYTES` | no | `1048576` | Applies to OCR.space only. Larger *images* are downscaled to ≤1600 px / JPEG 80 (Pillow) when available; otherwise they are `skipped` with "file larger than 1 MB, enter details manually". Tesseract reads the whole upload (max 5 MB). |
| `OCR_TESSERACT_LANG` | no | `eng+hin` | Tesseract languages; the Docker image installs English and Hindi. |
| `OCR_TESSERACT_TIMEOUT` | no | `120` | Seconds allowed per Tesseract / pdftoppm step. |
| `OCR_PDF_MAX_PAGES` | no | `5` | PDF pages read by Tesseract. |

## Local OCR with Tesseract (no daily limit)

`OCR_PROVIDER=tesseract` (or `hybrid`) runs the open-source Tesseract
engine on the same server as the portal: no API key, no daily or monthly
limit, and the document never leaves the server.

Tesseract is a system program, which Render's native Python runtime cannot
install. The repository's `Dockerfile` builds an image with Tesseract
(English + Hindi) and poppler (`pdftoppm`) and starts the app with
`scripts/docker-start.sh` (migrate, optional superuser, gunicorn on
`$PORT`). The native deploy (`build.sh`) keeps working unchanged; with
`tesseract` there, documents fail with "Tesseract is not installed on this
server" (with `hybrid` they fall back to OCR.space).

**Trade-offs on the free plan**

- Speed: about 10–60 s per image or PDF page on the shared CPU. It runs in
  the background, so uploads are not slowed down.
- Memory: one OCR job at a time (others wait), to stay within 512 MB.
- Accuracy: good on clear scans, weaker than OCR.space on blurred or tilted
  phone photos. `hybrid` covers those with OCR.space while quota remains.
  OCR output is only a suggestion either way.

### Try it on a separate Render service first

Leave the live service untouched until the Docker service is verified.

1. Render → **New → Web Service** → the same GitHub repo, branch `main`.
2. **Language / Runtime: Docker** (Render detects the `Dockerfile`).
   Instance type **Free**. Name e.g. `partner-portal-ocr-test`.
3. Environment: copy the variables from the live service (at least
   `DJANGO_SECRET_KEY`, `DATABASE_URL`, `RENDER=true`) and set
   `OCR_ENABLED=True`, `OCR_PROVIDER=tesseract`. Leave out `EMAIL_*`,
   `GMAIL_*`, `BREVO_*` and WhatsApp variables so the test service does
   not send real notifications. Ideally point `DATABASE_URL` at a Neon
   *branch* of the production database instead of production itself.
4. Deploy. The build log prints `tesseract --version` and the installed
   languages (`eng`, `hin`). No build or start command is needed; leave
   them empty so the `Dockerfile` `CMD` is used.
5. Upload test PAN / Aadhaar / PDF documents and check the OCR text and
   suggestions on the KYC review page.

### Switch the live service

When the test service works: live service → **Settings** → change the
runtime to **Docker** (if Render does not allow changing it, create the
Docker service as the new live service and move the custom domain), clear
the build/start commands, set `OCR_PROVIDER=tesseract` (or `hybrid`) and
deploy. To roll back OCR without redeploying code, set
`OCR_PROVIDER=ocrspace`.

## OCR.space free limits (`ocrspace` / `hybrid` fallback)

- **25,000** requests per month, **500** per day per IP address.
- Max file size **1 MB**, max **3 pages** for PDFs.
- Free tier requires a visible attribution/credit on the page when used
  in production — check their current terms.

## Privacy warning (read this before enabling)

With `OCR_PROVIDER=tesseract` documents are processed on the portal's own
server and are not sent to a third party. The warning below applies to
`ocrspace` and to the OCR.space fallback in `hybrid`.

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
