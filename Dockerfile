# ── build: venv + vendored event libs ────────────────────────────────────────
FROM cgr.void42.internal/chainguard/python:latest-dev AS build
USER root
ENV PIP_INDEX_URL=https://nexus.void42.internal/repository/pypi-proxy/simple/ \
    PIP_TRUSTED_HOST=nexus.void42.internal
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY vendor /tmp/vendor
RUN pip install --no-cache-dir /tmp/vendor/fontem-events /tmp/vendor/fontem-event-schemas

# ── runtime: distroless Chainguard python (was: ci-python runner image) ──────
FROM cgr.void42.internal/chainguard/python:latest
WORKDIR /app
COPY --from=build /venv /venv
ENV PATH="/venv/bin:$PATH" \
    METRICS_PORT=9100
COPY embedding_sink /app/embedding_sink
USER 65532
EXPOSE 9100
ENTRYPOINT ["/venv/bin/python"]
CMD ["-m", "embedding_sink"]
