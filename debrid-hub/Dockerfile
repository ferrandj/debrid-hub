FROM python:3.12-slim

# Docker Hub/GHCR don't read an icon from the image itself -- they pull it from
# the linked repo's social preview / avatar. Logo lives at docs/assets/logo.png.
LABEL org.opencontainers.image.title="Debrid Hub" \
      org.opencontainers.image.description="Aggregate direct download links across debrid services (Real-Debrid, AllDebrid, TorBox) for JDownloader2." \
      org.opencontainers.image.source="https://github.com/ferrandj/debrid-hub"

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health').status==200 else 1)"

CMD ["debrid-hub", "serve", "--host", "0.0.0.0", "--port", "8080"]
