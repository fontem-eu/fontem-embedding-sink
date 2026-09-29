# ── build: venv + vendored event libs ────────────────────────────────────────
FROM cgr.void42.internal/chainguard/python:latest-dev@sha256:5eef76bbb8d9f815317da126075705202b8ca5c2a151d723e7ecdf0373d9d861 AS build
USER root
ENV PIP_INDEX_URL=https://nexus.void42.internal/repository/pypi-proxy/simple/ \
    PIP_TRUSTED_HOST=nexus.void42.internal
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY vendor /tmp/vendor
RUN pip install --no-cache-dir /tmp/vendor/fontem-events /tmp/vendor/fontem-event-schemas
# The runtime needs the packages in the venv, not the tool that installed
# them: pip in a runtime image fetches and installs code (docker-build-sign
# checks runtime images for it).
RUN pip uninstall -y pip

# ── runtime: distroless Chainguard python (was: ci-python runner image) ──────
FROM cgr.void42.internal/chainguard/python:latest@sha256:a1775c7276078865461ee5714954284f12809f333433d856d720b249c65c11b2
WORKDIR /app
COPY --from=build /venv /venv
ENV PATH="/venv/bin:$PATH" \
    METRICS_PORT=9100
COPY embedding_sink /app/embedding_sink
USER 65532
EXPOSE 9100
ENTRYPOINT ["/venv/bin/python"]
CMD ["-m", "embedding_sink"]
