FROM python:3.14.2-slim

WORKDIR /app
COPY ./requirements.txt /app

RUN pip install --upgrade pip
RUN PIP_NO_BINARY=numpy pip install --no-cache-dir -r requirements.txt