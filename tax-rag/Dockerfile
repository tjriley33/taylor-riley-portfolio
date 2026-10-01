FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 TAXRAG_DATA_DIR=/data
WORKDIR /app
COPY pyproject.toml README.md ./
COPY taxrag ./taxrag
RUN pip install --no-cache-dir -e ".[aws]"
# Pre-download the ONNX models so cold starts don't hit Hugging Face.
RUN python -c "from taxrag.embed import embed_passages, cross_scores; embed_passages(['warm']); cross_scores('q', ['p'])"
VOLUME ["/data"]
EXPOSE 8000
# On start: pull the index from S3 if TAXRAG_S3_BUCKET is set, then serve.
CMD ["sh", "-c", "if [ -n \"$TAXRAG_S3_BUCKET\" ]; then taxrag sync pull; fi; taxrag serve --port 8000"]
