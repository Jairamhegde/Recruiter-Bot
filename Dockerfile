FROM python:3.12-slim

# Don't write .pyc files, and print logs immediately instead of buffering them.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first, so changing the code doesn't reinstall them.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY recruiter_bot/ recruiter_bot/
COPY migrations/ migrations/
COPY seed/ seed/
COPY frontend/ frontend/

# Runs as an unprivileged user, not root.
RUN useradd --create-home app
USER app

EXPOSE 8000

# On every start: bring the schema up to date, load seed records that aren't stored yet, then serve.
# Both steps are safe to repeat.
CMD ["sh", "-c", "python -m recruiter_bot.migrate && python -m recruiter_bot.seed && uvicorn recruiter_bot.api.main:app --host 0.0.0.0 --port 8000"]
