# fontem-embedding-sink — thin FastAPI-less consumer.
# Uses the shared void42 ci-python image (Nexus-proxied pip, curl, ca).
FROM gitea-http.dev-tools.svc.cluster.local:3000/void42/ci-python:latest

WORKDIR /app

# Vendored fontem-events + fontem-event-schemas match the pattern used
# by fontem-neo4j-sink. Update via `make vendor` on schema bumps.
COPY vendor /app/vendor
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
 && pip install --no-cache-dir /app/vendor/fontem-events \
                               /app/vendor/fontem-event-schemas

COPY embedding_sink /app/embedding_sink

# Non-root — cluster policy. See gitops/cluster-policies/disallow-privileged.yaml
RUN chown -R 65532:65532 /app
USER 65532

ENV METRICS_PORT=9100
EXPOSE 9100

CMD ["python", "-m", "embedding_sink"]
