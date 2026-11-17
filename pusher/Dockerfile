# Image for the one-shot pusher. Build with the pusher folder as the context:
#   docker build -t retail-gen-pusher pusher/
FROM python:3.12.8-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Run as a non-root user with no home and no login shell
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin pusher

WORKDIR /app
COPY . /app/pusher

USER pusher
ENTRYPOINT ["python", "-m", "pusher"]
