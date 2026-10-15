# Partner Portal image for Render (Docker runtime) with local OCR.
#
# Same app as the native Python deploy (build.sh), plus the Tesseract OCR
# engine (English + Hindi) and poppler's pdftoppm for PDFs, so
# OCR_PROVIDER=tesseract / hybrid can run on the server itself.
# Migrations run when the container starts (the database is not reachable
# during the image build). See docs/ocr.md.

FROM python:3.14-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OMP_THREAD_LIMIT=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-hin \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && tesseract --version \
    && tesseract --list-langs

WORKDIR /app

COPY requirements.txt .
# Pillow shrinks very large photos before OCR (optional at runtime).
RUN pip install -r requirements.txt Pillow==12.3.0

COPY . .

# Collect static files at build time. The secret is a throwaway used only
# for this step; the real DJANGO_SECRET_KEY comes from Render at runtime.
RUN DJANGO_SECRET_KEY=collectstatic-only DJANGO_DEBUG=False \
    python manage.py collectstatic --no-input \
    && chmod +x scripts/docker-start.sh \
    && useradd --create-home --uid 1000 app \
    && chown -R app:app /app

USER app

EXPOSE 10000
CMD ["scripts/docker-start.sh"]
