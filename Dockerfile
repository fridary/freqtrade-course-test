FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    git \
    curl \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /freqtrade

RUN pip install --upgrade pip setuptools wheel

COPY requirements.txt ./
RUN pip install -r requirements.txt

# pandas_ta — кладём папку напрямую в site-packages
# (пакет убран с PyPI, устанавливаем вручную из conda окружения)
COPY vendor_packages/pandas_ta/pandas_ta /usr/local/lib/python3.11/site-packages/pandas_ta

RUN mkdir -p /freqtrade/user_data /freqtrade/data

ENV PYTHONPATH=/freqtrade

ENTRYPOINT ["python", "-m", "freqtrade"]