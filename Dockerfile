FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml uv.lock README.md ./

RUN uv sync --frozen --no-install-project

COPY src/ src/
COPY streamlit_app.py ./

RUN uv sync --frozen

EXPOSE 8501

CMD ["uv", "run", "streamlit", "run", "streamlit_app.py", \
     "--server.port=8501", "--server.address=0.0.0.0"]
