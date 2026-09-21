FROM python:3.10-slim

# 시스템 필수 유틸리티 설치
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    unixodbc \
    unixodbc-dev \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Microsoft 공식 GPG 키 등록 및 저장소 추가 (apt-key 대신 gpg keyring 방식 사용)
RUN curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /etc/apt/trusted.gpg.d/microsoft.gpg \
    && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql17 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 파이썬 의존성 패키지 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 전체 소스 코드 복사
COPY . .

EXPOSE 8501

# Streamlit 실행
CMD streamlit run app.py --server.port $PORT --server.address 0.0.0.0
