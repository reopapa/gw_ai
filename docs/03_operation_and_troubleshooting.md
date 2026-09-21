# 03. 운영, 배포 및 트러블슈팅 가이드 (Operation & Troubleshooting)

본 문서는 사내 그룹웨어 AI 기안/품의서 초안 생성 도우미의 환경 설정, 서비스 구동, 배치 운영, 실무 트러블슈팅 사례 및 향후 개선 과제를 기술합니다.

---

## 💻 1. 실행 환경 및 종속성 구성

### 1.1. 시스템 요구사항
- **운영체제:** Windows 10/11 또는 Windows Server 2016+ (사내 MSSQL 통신 가능한 환경)
- **Python 버전:** Python 3.10 이상 권장
- **ODBC 드라이버:** Microsoft ODBC Driver 18 for SQL Server 필수 설치
  - [MS 공식 다운로드 링크](https://learn.microsoft.com/ko-kr/sql/connect/odbc/download-odbc-driver-for-sql-server)
  - 설치 확인 명령: `powershell "Get-OdbcDriver -Name '*SQL Server*'"`

### 1.2. 필수 Python 패키지 설치
프로젝트 루트에서 다음 명령으로 라이브러리를 설치합니다:

```bash
pip install streamlit google-genai cohere pyodbc pandas openpyxl beautifulsoup4 markdownify requests
```

| 패키지명 | 버전 권장 | 주요 용도 |
| :--- | :--- | :--- |
| `streamlit` | 1.30.0+ | 사용자 웹 인터페이스 프레임워크 |
| `google-genai` | 최신 | Google Gemini 공식 SDK (`genai.Client`) |
| `cohere` | 5.0.0+ | Cohere Rerank API 클라이언트 |
| `pyodbc` | 4.0.35+ | MSSQL 데이터베이스 연결 및 쿼리 |
| `pandas`, `openpyxl` | 최신 | 엑셀 파일 전처리 및 마크다운 표 변환 |
| `beautifulsoup4`, `markdownify` | 최신 | HTML 파싱, 문단 분할, 텍스트 변환 |

---

## ⚙️ 2. 환경 설정 가이드 (`.env` & `config.py`)

시스템의 모든 보안 민감 정보(API Key, DB 비밀번호)는 **`.env` 환경변수 파일**로 철저히 분리되어 관리되며, [config.py](file:///c:/AI/gw_ai/config.py)는 `python-dotenv`를 통해 이를 시스템에 로드합니다.

### 2.1. 환경설정 파일 구조
- **`.env` (로컬 전용, 보안 파일):** 실제 비밀번호와 API 키가 저장되는 파일로, `.gitignore`에 등록되어 Git 커밋 및 외부 압축 전달에서 제외됩니다.
- **`.env.example` (배포/인수인계 템플릿):** 신규 인계자가 복사하여 사용할 수 있도록 키 자리가 비어 있는 템플릿 파일입니다.

### 2.2. 신규 인계자 환경 구성 절차
```bash
# 1. 템플릿을 복사하여 .env 생성
copy .env.example .env

# 2. .env 파일을 메모장이나 에디터로 열어 실제 정보 입력
```

```ini
# .env 설정 예시
GEMINI_API_KEY=AIzaSy...                # Google AI Studio 발급 키
GEMINI_MODEL=gemini-3-flash-preview     # 기본 추론 모델

COHERE_API_KEY=EJkrqjh...               # Cohere 대시보드 발급 키

# 소스 DB (CrewCloud 실운영)
DB_A_SERVER=192.9.200.51,1433
DB_A_DATABASE=CrewCloud_Company
DB_A_UID=tkadmin
DB_A_PWD=실제_비밀번호

# 타겟 DB (MES/AI 결과 저장소)
DB_B_SERVER=192.9.200.18,14333
DB_B_DATABASE=AI_TAEKYUNG
DB_B_UID=tkadmin
DB_B_PWD=실제_비밀번호
```

> [!IMPORTANT]
> **보안 원칙 준수**  
> `.env` 파일은 절대 Git 저장소에 커밋하거나 외부 메일로 발송하지 마십시오. 신규 담당자에게 프로젝트를 전달할 때는 `.env.example` 템플릿이 포함된 상태로 전달하고, 비밀번호는 사내 보안 메신저 등 별도 경로로 안내하십시오.

---

## 🚀 3. 서비스 구동 및 운영 가이드

### 3.1. 메인 웹 인터페이스 실행 (`app.py`)
사용자 테스트 및 실제 기안서 작성을 위한 Streamlit 웹 서비스를 기동합니다.

```bash
# 기본 실행 (로컬 브라우저 자동 오픈, 기본 포트 8501)
streamlit run app.py

# 포트 변경 및 외부 접속 허용 시
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

### 3.2. 과거 결재 문서 배치 색인 실행 (`gw_ai.py`)
신규 승인 결재 문서를 배치 분석하여 타겟 DB `EAPPDocument_AI` 테이블에 메타데이터(키워드 및 요약)를 적재할 때 실행합니다.

```bash
# config.py의 START_DATE ~ END_DATE 기간 동안의 문서를 배치 처리
python gw_ai.py
```
- 실패 레코드는 `Keywords='ERROR'`로 기록되며, 다음 실행 시 `get_processed_ids(include_errors=False)`에 의해 자동으로 재시도 대상에 포함됩니다.

### 3.3. 단독 테스트 스크립트 (`draft_generator.py`)
UI 없이 백엔드 생성 로직만 검증하고 싶을 때 사용합니다.
```bash
python draft_generator.py
```

---

## ⚡ 4. Streamlit 운영 핵심 주의사항

### 4.1. 캐시 무효화 (`@st.cache_resource`)
Streamlit은 성능 최적화를 위해 `@st.cache_resource` 데코레이터를 통해 `Processor` 및 `DatabaseManager` 인스턴스를 프로세스 메모리에 싱글톤으로 유지합니다.

```python
# app.py
@st.cache_resource
def get_processor_v13():
    return Processor(GEMINI_API_KEY, GEMINI_MODEL, COHERE_API_KEY)
```

> [!WARNING]
> `processor.py`의 파싱 로직, 프롬프트, 메서드를 수정한 뒤 Streamlit 웹 화면을 새로고침(F5)해도 **메모리에 이미 캐시된 구버전 `Processor` 객체가 계속 실행**될 수 있습니다.  
> **해결책:**
> 1. `app.py`에서 함수명을 `get_processor_v14()`로 변경하여 캐시를 강제 무효화하거나,
> 2. 터미널에서 Streamlit 프로세스를 완전히 종료(`Ctrl + C`) 후 재시작하십시오.

### 4.2. Streamlit 렌더링 생명주기와 고스팅(Ghosting) 방지
Streamlit은 사용자가 버튼을 클릭하거나 위젯 값을 변경할 때마다 스크립트 전체를 위에서부터 아래로 다시 실행(Rerun)합니다.
- 복잡한 작업(단계 전환, 폼 제출)을 단순 `if st.button(...):` 블록 안에서 처리하면 이전 폼과 새 폼이 화면에 중복으로 번쩍이는 **고스팅(Ghosting)** 현상이 발생합니다.
- 따라서 상태 변경 및 데이터 처리는 반드시 **`on_click` 콜백 함수** 내부에서 `st.session_state`를 수정한 후 렌더링 흐름으로 넘기도록 패턴화되어 있습니다.

---

## 🛠️ 5. 빈발 이슈 및 트러블슈팅 사례 (Troubleshooting)

실제 개발 및 테스트 과정에서 발생했던 주요 이슈와 검증된 해결 방법입니다. (상세 내역은 [issue_and_resolution_history.md](file:///c:/AI/gw_ai/issue_and_resolution_history.md) 참조)

### 5.1. 3단계 팩트체크 보드 진입 시 `JSON Parsing Error`
- **증상:** AI가 순수 JSON 외에 앞뒤에 `Here is the JSON result:` 같은 자연어 부연 설명을 덧붙여 파싱 에러 발생.
- **해결책:** `processor.py`에서 정규식으로 문자열의 가장 첫 번째 `[` (또는 `{`)와 마지막 `]` (또는 `}`) 사이의 순수 JSON 본문만 슬라이싱하여 파싱하도록 방어 로직 구축.

### 5.2. 3단계에서 제외한 항목이 4단계 초안에 그대로 출력되는 문제
- **증상:** 사용자가 체크박스를 해제하여 제외한 항목이 과거 참고 문서 서식에 있다는 이유로 AI가 초안에 임의 작성함.
- **해결책:** 제외된 항목 리스트(`excluded_items`)를 수집하여 초안 생성 프롬프트에 **"사용자가 명시적으로 제외하도록 선택한 항목이므로 과거 참고 문서에 있더라도 절대 생성하지 말 것"**이라는 강력한 네거티브 프롬프트(부정 지시어)를 주입하여 100% 차단.

### 5.3. 4단계 도출 근거(Grounding) 표기 오매칭 버그
- **증상:** 본문 단락 내에 단어 하나만 스쳐도(`any`) 엉뚱한 단락에 출처/근거가 잘못 표시되는 현상.
- **해결책:** 본문 검색 방식을 전면 폐기하고, **"단락의 제목(`<h>` 태그 텍스트)"과 "체크리스트 핵심어" 간의 문자열 일치율이 50% 이상일 때만 매칭**되도록 엄격한 자카드/교집합 알고리즘을 적용하여 오매칭 해결.

### 5.4. 4단계 '이전단계' 클릭 시 2단계로 건너뛰는 라우팅 오류
- **증상:** 4단계에서 '이전단계' 버튼 클릭 시 3단계(팩트체크 보드)가 아닌 2단계로 점프함.
- **해결책:** 초기 개발 당시 하드코딩되었던 `st.session_state.step = 2`를 `st.session_state.step = 3`으로 수정 완료.

---

## 📈 6. 향후 고도화 로드맵 (Roadmap)

시스템의 엔터프라이즈 완성도를 높이기 위해 인계자가 향후 구현을 검토할 수 있는 기술 과제입니다. (상세 내역: [future_improvements.md](file:///c:/AI/gw_ai/future_improvements.md))

1. **실시간 텍스트 스트리밍 (Streaming):**
   - 4단계 초안 생성 시 사용자 체감 대기시간을 줄이기 위해 `client.models.generate_content_stream`을 적용하여 화면에 타자기처럼 출력되도록 개선.
2. **API Rate Limit 방어 (지수 백오프):**
   - Gemini API 429 에러 발생에 대비하여 `tenacity` 라이브러리를 활용한 지수 백오프(Exponential Backoff) 기반 자동 재시도 로직 탑재.
3. **임시 파일 주기적 정제 (Garbage Collection):**
   - 비정상 종료 시에도 `uploads/` 디렉토리에 생성된 임시 엑셀/텍스트 파일이 24시간 후 자동 삭제되도록 클린업 데몬 구현.
4. **개인정보/민감정보 (PII) 로컬 마스킹:**
   - 첨부파일이나 결재 문서에 포함된 주민등록번호, 계좌번호, 전화번호를 정규식(Regex)으로 사내 로컬에서 먼저 `***` 마스킹한 후 AI에 전송하여 보안 컴플라이언스 준수.
5. **벡터 데이터베이스 연동 하이브리드 검색:**
   - 문서 수가 수만 건으로 증가할 경우를 대비하여 Chroma, Qdrant, 또는 MSSQL 2025 Vector Extension을 연동한 Dense + Sparse 하이브리드 RAG 구축.
