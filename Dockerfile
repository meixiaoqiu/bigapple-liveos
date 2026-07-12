FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV BIG_APPLE_ENV=development
ENV DJANGO_DEBUG=true

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        default-libmysqlclient-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY . /app

RUN python -m pip install --upgrade pip \
    && python -m pip install -e ".[mysql,dev]"

EXPOSE 20100 20101 20102

# Development smoke image only. Production deploys must override env and command.
CMD ["python", "manage.py", "runserver", "0.0.0.0:20100"]
