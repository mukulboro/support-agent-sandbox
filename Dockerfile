FROM python:3.12-slim

# Package index used for the build. Override with a nearer mirror if PyPI is slow: PYPI_MIRROR=... docker compose build
ARG PYPI_MIRROR=https://pypi.org/simple

RUN pip install --no-cache-dir --index-url $PYPI_MIRROR uv
WORKDIR /srv

# uv.lock pins every package and hash, so the same files are installed whichever index serves them
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --output-file requirements.txt \
    && uv pip install --system --no-cache --index-url $PYPI_MIRROR -r requirements.txt

COPY app ./app
COPY docs ./docs
EXPOSE 8000
CMD ["uvicorn", "app.http.server:app", "--host", "0.0.0.0", "--port", "8000"]
