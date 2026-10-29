FROM python:3.12-slim

# Don't write .pyc files, and print logs immediately instead of buffering them.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first, so changing the code doesn't reinstall them.
COPY requirements.txt requirements-linking.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# The model stage of word linking is optional (D-54) and off by default: the image runs on the rules alone.
# Build with WITH_MODELS=true (docker compose passes it through) to add the models, about 125 MB plus libraries.
# If their libraries or files can't be fetched, the image still builds and linking uses the rules alone.
ARG WITH_MODELS=false
RUN if [ "$WITH_MODELS" = "true" ]; then \
        pip install --no-cache-dir -r requirements-linking.txt || echo "model libraries not installed: rules only"; \
    fi

COPY recruiter_bot/ recruiter_bot/
COPY migrations/ migrations/
COPY seed/ seed/

# Downloads the two models from pinned commits and checks each file's SHA-256 (D-42).
RUN if [ "$WITH_MODELS" = "true" ]; then \
        python -m recruiter_bot.linking.model_files || echo "model files not downloaded: rules only"; \
    fi

# Runs as an unprivileged user, not root.
RUN useradd --create-home app
USER app

EXPOSE 8000

# On every start: bring the schema up to date, load seed records that aren't stored yet, then serve.
# Both steps are safe to repeat (D-39, D-46).
CMD ["sh", "-c", "python -m recruiter_bot.migrate && python -m recruiter_bot.seed && uvicorn recruiter_bot.api.main:app --host 0.0.0.0 --port 8000"]
