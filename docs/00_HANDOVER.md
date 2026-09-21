# AI 기안/품의서 초안 생성 도우미 - 인수인계 종합 가이드 (Handover Master Guide)

본 문서는 **그룹웨어 전자결재 연동 'AI 기안/품의서 초안 생성기'** 프로젝트의 인수인계를 위해 작성된 마스터 가이드입니다. 신규 담당자가 프로젝트의 목적, 구조, 구동 방법, 핵심 AI 파이프라인 및 운영 시 주의사항을 한눈에 파악하고 즉시 유지보수 및 고도화 작업을 수행할 수 있도록 구성되었습니다.

---

## 📌 1. 프로젝트 개요 (Overview)

- **프로젝트명:** 사내 그룹웨어 AI 기안/품의서 초안 생성 도우미
- **목적:** 사내 사용자가 작성하려는 기안의 핵심 요약 및 첨부파일(견적서, 구매내역 등)을 제공하면, 과거 3년 치 승인 결재 문서 및 첨부파일 데이터를 종합 분석하여 그룹웨어 표준 양식에 맞춘 완성도 높은 **HTML 결재 초안을 5분 이내에 자동 생성**
- **주요 기술 스택:**
  - **프론트엔드/UI:** Python Streamlit (반응형 4단계 위젯, Custom CSS/HTML, Session State)
  - **AI 엔진:** Google Gemini API (`gemini-3-flash-preview` / `gemini-1.5-flash`), Cohere Rerank API (`rerank-v3.5`)
  - **백엔드/데이터 처리:** Python 3.10+, Pandas, BeautifulSoup4, Markdownify, Concurrent.Futures (병렬 처리)
  - **데이터베이스:** Microsoft SQL Server (ODBC Driver 18)
    - 소스 DB: 그룹웨어 실운영 DB (`CrewCloud_Company`)
    - 타겟 DB: AI 메타데이터 및 결과 저장소 (`AI_TAEKYUNG`)

---

## 🗂️ 2. 인수인계 문서 맵 (Documentation Map)

프로젝트와 관련된 상세 기술 문서는 `docs/` 디렉토리에 체계적으로 분류되어 있습니다.

| 번호 | 문서명 | 링크 | 주요 내용 |
| :--- | :--- | :--- | :--- |
| **01** | **시스템 아키텍처 및 상세 설계서** | [01_system_architecture_and_design.md](file:///c:/AI/gw_ai/docs/01_system_architecture_and_design.md) | 전체 시스템 구조도, 4단계 파이프라인 시퀀스 다이어그램, DB 스키마 명세, 클래스/함수 인터페이스 |
| **02** | **AI 파이프라인 및 프롬프트 가이드** | [02_ai_pipeline_and_prompts.md](file:///c:/AI/gw_ai/docs/02_ai_pipeline_and_prompts.md) | 2단계 RAG 검색, 첨부파일 전처리(엑셀 파싱 절대 규칙), 팩트체크, 단락별 부분 수정, 프롬프트 모음 |
| **03** | **운영, 배포 및 트러블슈팅 가이드** | [03_operation_and_troubleshooting.md](file:///c:/AI/gw_ai/docs/03_operation_and_troubleshooting.md) | 실행 환경 구성, `config.py` 설정, Streamlit 캐시 주의사항, 빈발 이슈 해결책, 향후 로드맵 |
| **참조** | **프로세스 정의 요약서** | [project_process_summary.md](file:///c:/AI/gw_ai/project_process_summary.md) | 프로젝트 핵심 프로세스 및 프롬프트 엔지니어링 주의사항 요약 |
| **참조** | **이슈 및 변경 히스토리** | [issue_and_resolution_history.md](file:///c:/AI/gw_ai/issue_and_resolution_history.md) | 실무 오류 수정 및 기능 개선 누적 로그 (Changelog) |
| **참조** | **향후 개선 과제** | [future_improvements.md](file:///c:/AI/gw_ai/future_improvements.md) | 스트리밍, PII 마스킹, 하이브리드 검색 등 향후 고도화 항목 |

---

## 📂 3. 디렉토리 및 파일 구조

```plaintext
c:\AI\gw_ai\
├── docs/                               # 📖 인수인계 상세 기술 문서
│   ├── 00_HANDOVER.md                  # [본 문서] 인수인계 마스터 가이드
│   ├── 01_system_architecture_and_design.md   # 시스템 설계 및 DB 스키마
│   ├── 02_ai_pipeline_and_prompts.md          # RAG, 파서, 프롬프트 가이드
│   └── 03_operation_and_troubleshooting.md    # 실행, 배포, 캐시, 트러블슈팅
│
├── app.py                              # Streamlit 기반 메인 웹 애플리케이션 (STEP 1~4)
├── processor.py                        # Gemini/Cohere API 연동, 파싱, RAG, 초안 생성 핵심 모듈
├── database.py                         # MSSQL 연결 관리, 쿼리, 이력/로그 저장 모듈
├── config.py                           # .env 환경변수 로딩 및 시스템 설정 모듈
├── .env                                # 로컬 실제 환경변수 (보안 파일, 압축/Git 제외)
├── .env.example                        # 신규 인계자 전달용 환경설정 템플릿
├── .gitignore                          # 보안 및 불필요 파일 형상관리 제외 설정
├── requirements.txt                    # 필수 Python 라이브러리 목록
├── run.bat                             # 윈도우 원클릭 자동 실행 배치 스크립트
├── gw_ai.py                            # 과거 결재문서 일괄 분석 및 메타데이터 색인 배치 스크립트
├── draft_generator.py                  # 단독 초안 생성 테스트 스크립트
├── project_process_summary.md          # 프로젝트 프로세스 정의 및 핵심 가이드
├── issue_and_resolution_history.md     # 버그 수정 및 개선 이력 (Changelog)
├── future_improvements.md              # 향후 고도화 및 기술 과제 백로그
│
├── uploads/                            # 첨부파일 임시 업로드 폴더
└── .agents/
    └── AGENTS.md                       # AI 에이전트 지침 및 개발 불변 규칙
```

---

## 🚀 4. 빠른 시작 가이드 (Quick Start)

### 4.1. 필수 실행 환경
- Windows 10/11 또는 Windows Server
- Python 3.10 이상
- Microsoft ODBC Driver 18 for SQL Server 설치 필수
- 사내 네트워크(또는 VPN) 연결 필수 (내부 DB 192.9.200.x 접근용)

### 4.2. 원클릭 실행 (가장 추천)
프로젝트 폴더의 **`run.bat`** 파일을 더블클릭하면 라이브러리 자동 점검 후 웹 브라우저(`http://localhost:8501`)가 바로 열립니다.

### 4.3. 수동 패키지 설치 및 환경설정
```bash
# 1. 라이브러리 설치
pip install -r requirements.txt

# 2. 환경설정 파일 준비 (.env.example 복사 후 실제 키/비밀번호 입력)
copy .env.example .env
# .env 파일을 열어 GEMINI_API_KEY, COHERE_API_KEY, DB 접속 패스워드 입력

# 3. 애플리케이션 실행
streamlit run app.py
```

# 2. 과거 결재 데이터 색인 배치 실행 (필요 시)
python gw_ai.py
```

---

## ⚠️ 5. 인수인계 시 반드시 지켜야 할 절대 불변 규칙

프로젝트 유지보수 시 다음 두 가지 규칙은 **시스템 품질 유지의 핵심**이므로 절대 임의로 변경하거나 삭제해서는 안 됩니다.

> [!CAUTION]
> ### 1. 첨부파일(엑셀) 파싱 로직 보존 (`processor.py`)
> 현재 `processor.py`의 `upload_file()` 내부에 구현된 **`pandas` 기반 빈 행/열 dropna 및 마크다운 표 변환 로직**은 복잡한 견적서의 병합 셀/빈 셀로 인한 LLM의 숫자 왜곡 및 행 밀림 현상을 완벽히 해결한 검증된 로직입니다.  
> 엑셀 원본 파일(`.xlsx`)을 그대로 구글 파일 API로 올리면 모델이 서식을 오독하여 **견적 금액 오류(치명적 결함)**가 발생하므로, 마크다운 표 변환 파이프라인을 엄격히 유지해야 합니다.

> [!IMPORTANT]
> ### 2. 아키텍처 문서 동기화 (`project_process_summary.md`)
> 시스템의 핵심 아키텍처, 4단계 워크플로우, 데이터베이스 스키마, 또는 AI 프로세스가 변경될 경우 루트 디렉토리의 [project_process_summary.md](file:///c:/AI/gw_ai/project_process_summary.md) 및 [docs/](file:///c:/AI/gw_ai/docs/) 문서를 즉시 갱신해야 합니다.

> [!WARNING]
> ### 3. Streamlit 캐시 무효화 (`@st.cache_resource`)
> `processor.py`의 함수 로직이나 프롬프트를 수정한 후 화면에 반영되지 않는 경우가 있습니다. Streamlit이 `get_processor_v13()` 등 `@st.cache_resource`로 메모리에 인스턴스를 유지하기 때문입니다. 코드 수정 후에는 반드시 **함수 버전 번호를 올리거나(예: `get_processor_v14`), Streamlit 프로세스를 재시작**해야 합니다.

---

## 👥 6. 담당자 체크리스트

신규 인계자는 업무 착수 전 다음 사항을 순서대로 점검하십시오:

- [ ] `config.py`의 MSSQL 소스/타겟 DB 접속 테스트 (사내망 또는 VPN 연결 상태)
- [ ] Gemini API 및 Cohere API의 월간 쿼터/크레딧 유효성 확인
- [ ] `streamlit run app.py` 구동 후 샘플 기안서 생성 테스트 (1단계 ~ 4단계 전체 플로우)
- [ ] 2단계에서 첨부파일(엑셀/이미지) 업로드 후 3단계 팩트체크 보드에 금액/품목이 정상 추출되는지 확인
- [ ] 4단계 생성된 초안의 단락별 개별 수정(Comment 팝업) 및 '최종 수정 반영' 동작 확인
- [ ] MSSQL 타겟 DB `AI_TAEKYUNG`의 `EAPPDocument_AI_Result` 및 `EAPPDocument_AI_ChatLog`에 이력이 정상 적재되는지 확인

세부 기술 명세는 다음 문서인 **[01_system_architecture_and_design.md](file:///c:/AI/gw_ai/docs/01_system_architecture_and_design.md)**에서 확인하십시오.
