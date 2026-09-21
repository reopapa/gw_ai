import os
from dotenv import load_dotenv

# .env 파일 로드 (존재할 경우 시스템 환경변수로 등록)
load_dotenv()

# ========================================================
# 1. Google Gemini API 설정
# ========================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

# ========================================================
# 2. OpenAI API 설정
# ========================================================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-6-astra")

# ========================================================
# 3. Cohere Reranker API 설정
# ========================================================
COHERE_API_KEY = os.getenv("COHERE_API_KEY", "")

# ========================================================
# 3. 서버 A (소스 DB - CrewCloud 실운영) 설정
# ========================================================
DB_CONFIG_A = {
    "DRIVER": os.getenv("DB_A_DRIVER", "{ODBC Driver 17 for SQL Server}"),
    "SERVER": os.getenv("DB_A_SERVER", "192.9.200.51,1433"),
    "DATABASE": os.getenv("DB_A_DATABASE", "CrewCloud_Company"),
    "UID": os.getenv("DB_A_UID", "tkadmin"),
    "PWD": os.getenv("DB_A_PWD", ""),
    "TRUST_CERT": os.getenv("DB_A_TRUST_CERT", "yes")
}

# ========================================================
# 4. 서버 B (타겟 DB - MES / AI) 설정
# ========================================================
DB_CONFIG_B = {
    "DRIVER": os.getenv("DB_B_DRIVER", "{ODBC Driver 17 for SQL Server}"),
    "SERVER": os.getenv("DB_B_SERVER", "192.9.200.18,14333"),
    "DATABASE": os.getenv("DB_B_DATABASE", "AI_TAEKYUNG"),
    "UID": os.getenv("DB_B_UID", "tkadmin"),
    "PWD": os.getenv("DB_B_PWD", ""),
    "TRUST_CERT": os.getenv("DB_B_TRUST_CERT", "yes")
}

# ========================================================
# 5. 테이블 및 배치 파라미터
# ========================================================
TABLE_AI = os.getenv("TABLE_AI", "EAPPDocument_AI")
START_DATE = os.getenv("START_DATE", "2026-05-26")
END_DATE = os.getenv("END_DATE", "2026-05-31")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "5"))

# ========================================================
# 6. 조회 쿼리 (서버 A용) - 날짜 파라미터 2개: (날짜, 다음날)
# ========================================================
QUERY_A = """
SELECT 
    A.ID,
    A.Title,
    A.Content,
    A.WriterID,
    C.Name AS 'Writer',
    A.DepartID,
    A.DeptName1,
    A.RegDate,
    A.ValDate,
    A.IsDelete,
    A.State,
    A.FormID,
    A.Serial,
    A.OperationDate,
    X.SerialType AS 'FormName',
    X.SerialType AS 'EACode'
FROM EAPPDocument AS A
INNER JOIN Organization_Users AS C ON A.WriterID = C.UserID
CROSS APPLY (
    SELECT SUBSTRING(
        A.Serial,
        CHARINDEX('-', A.Serial) + 1,
        CHARINDEX('-', A.Serial, CHARINDEX('-', A.Serial) + 1) - CHARINDEX('-', A.Serial) - 1
    ) AS SerialType
) AS X
WHERE A.State = 400 
    AND (A.OperationDate >= ? AND A.OperationDate < ?)
    AND X.SerialType IN ('기안','업무','보고','대공','대수','공고','공지','회의','전공', '검수', '구매')
"""
