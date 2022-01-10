FROM python:3.9.9-slim-buster

ENV PYTHONPATH "${PYTHONPATH}:/code"
ENV PATH "/code:${PATH}"

WORKDIR /code

RUN pip install poetry

COPY poetry.lock pyproject.toml /code/

RUN poetry config virtualenvs.create false && poetry install --no-interaction --no-ansi

COPY . /code/