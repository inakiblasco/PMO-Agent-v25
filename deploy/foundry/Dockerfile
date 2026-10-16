FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY skills ./skills

RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

ENV PMO_RUNTIME=foundry
ENV PMO_SKILLS_DIR=/app/skills

EXPOSE 8088

USER appuser

CMD ["fde-pmo-host"]
