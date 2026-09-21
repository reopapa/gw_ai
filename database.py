import pyodbc
import json

class DatabaseManager:
    def __init__(self, config):
        self.conn_str = (
            f"DRIVER={config['DRIVER']};"
            f"SERVER={config['SERVER']};"
            f"DATABASE={config['DATABASE']};"
            f"UID={config['UID']};"
            f"PWD={config['PWD']};"
            f"TrustServerCertificate={config.get('TRUST_CERT', 'no')};"
        )
        self.conn = None

    def connect(self):
        self.conn = pyodbc.connect(self.conn_str)
        return self.conn

    def close(self):
        if self.conn:
            self.conn.close()

    def fetch_all(self, query):
        cursor = self.conn.cursor()
        cursor.execute(query)
        columns = [column[0] for column in cursor.description]
        rows = cursor.fetchall()
        return columns, rows

    def fetch_all_with_params(self, query, params):
        """파라미터 바인딩을 사용하여 쿼리 실행"""
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        columns = [column[0] for column in cursor.description]
        rows = cursor.fetchall()
        return columns, rows

    def execute(self, query, params=None):
        cursor = self.conn.cursor()
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        self.conn.commit()

    def get_processed_ids(self, table_name, include_errors=False):
        """이미 처리되어 저장된 ID 목록 반환
        include_errors 가 False 인 경우, 처리 중 에러(Keywords='ERROR')가 발생했던 레코드는 
        목록에서 제외하여 메인 프로그램(gw_ai.py)이 신규 레코드로 인식하여 재처리하게 만듭니다.
        """
        try:
            cursor = self.conn.cursor()
            
            condition = ""
            if not include_errors:
                # 사용자의 요청에 따라 오직 Keywords 컬럼이 'ERROR'인지만 검사합니다.
                condition = " WHERE ISNULL(CAST(Keywords AS NVARCHAR(MAX)), '') <> 'ERROR' "
                
            # 테이블 존재 여부 확인 후 조회
            check_query = f"IF OBJECT_ID('{table_name}', 'U') IS NOT NULL SELECT ID FROM {table_name} {condition} ELSE SELECT 1 WHERE 1=0"
            cursor.execute(check_query)
            ids = [row[0] for row in cursor.fetchall()]
            return ids
        except Exception as e:
            print(f"[WARN] 처리된 ID 조회 중 오류 (테이블이 없을 수 있음): {e}")
            return []

    def ensure_vector_table_exists(self, table_name="EAPPDocument_AI"):
        """유사 문서 검색용 메타데이터 테이블 생성"""
        query = f'''
            IF OBJECT_ID('{table_name}', 'U') IS NULL
            BEGIN
                CREATE TABLE {table_name} (
                    ID INT PRIMARY KEY,
                    Title NVARCHAR(500),
                    WriterID NVARCHAR(50),
                    Writer NVARCHAR(50),
                    DepartID NVARCHAR(50),
                    DeptName1 NVARCHAR(100),
                    RegDate DATETIME,
                    Keywords NVARCHAR(MAX),
                    Summary NVARCHAR(MAX),
                    IsDelete BIT DEFAULT 0,
                    FormName NVARCHAR(40),
                    EACode NVARCHAR(20)
                )
            END
        '''
        self.execute(query)

    def ensure_table_exists(self, table_name="EAPPDocument_AI"):
        """기존 코드 호환성을 위한 ensure_vector_table_exists 별칭"""
        self.ensure_vector_table_exists(table_name)

    def ensure_result_table_exists(self, table_name="EAPPDocument_AI_Result"):
        """최종 AI 생성 결과를 저장할 테이블 생성 및 스키마 확장"""
        query = f'''
            IF OBJECT_ID('{table_name}', 'U') IS NULL
            BEGIN
                CREATE TABLE {table_name} (
                    No INT IDENTITY(1,1) PRIMARY KEY,
                    RequesterID NVARCHAR(50),
                    FormName NVARCHAR(100),
                    DocSummary NVARCHAR(MAX),
                    UploadedFiles NVARCHAR(MAX),
                    EssentialAnswers NVARCHAR(MAX),
                    ExtractedFacts NVARCHAR(MAX),
                    Detail1 NVARCHAR(MAX),
                    Detail2 NVARCHAR(MAX),
                    Detail3 NVARCHAR(MAX),
                    Detail4 NVARCHAR(MAX),
                    Detail5 NVARCHAR(MAX),
                    Detail6 NVARCHAR(MAX),
                    Detail7 NVARCHAR(MAX),
                    Detail8 NVARCHAR(MAX),
                    Detail9 NVARCHAR(MAX),
                    Detail10 NVARCHAR(MAX),
                    RequestContent NVARCHAR(MAX),
                    RefDocID1 INT,
                    RefDocTitle1 NVARCHAR(500),
                    RefDocScore1 FLOAT,
                    RefDocID2 INT,
                    RefDocTitle2 NVARCHAR(500),
                    RefDocScore2 FLOAT,
                    RefDocID3 INT,
                    RefDocTitle3 NVARCHAR(500),
                    RefDocScore3 FLOAT,
                    ResultContent NVARCHAR(MAX),
                    CreatedAt DATETIME DEFAULT GETDATE()
                )
            END
            ELSE
            BEGIN
                IF COL_LENGTH('{table_name}', 'RefDocScore1') IS NULL
                BEGIN
                    ALTER TABLE {table_name} ADD RefDocScore1 FLOAT;
                    ALTER TABLE {table_name} ADD RefDocScore2 FLOAT;
                    ALTER TABLE {table_name} ADD RefDocScore3 FLOAT;
                END
                IF COL_LENGTH('{table_name}', 'FormName') IS NULL
                BEGIN
                    ALTER TABLE {table_name} ADD FormName NVARCHAR(100);
                    ALTER TABLE {table_name} ADD DocSummary NVARCHAR(MAX);
                    ALTER TABLE {table_name} ADD UploadedFiles NVARCHAR(MAX);
                    ALTER TABLE {table_name} ADD EssentialAnswers NVARCHAR(MAX);
                    ALTER TABLE {table_name} ADD ExtractedFacts NVARCHAR(MAX);
                END
                IF COL_LENGTH('{table_name}', 'Detail1') IS NULL
                BEGIN
                    ALTER TABLE {table_name} ADD Detail1 NVARCHAR(MAX);
                    ALTER TABLE {table_name} ADD Detail2 NVARCHAR(MAX);
                    ALTER TABLE {table_name} ADD Detail3 NVARCHAR(MAX);
                    ALTER TABLE {table_name} ADD Detail4 NVARCHAR(MAX);
                    ALTER TABLE {table_name} ADD Detail5 NVARCHAR(MAX);
                    ALTER TABLE {table_name} ADD Detail6 NVARCHAR(MAX);
                    ALTER TABLE {table_name} ADD Detail7 NVARCHAR(MAX);
                    ALTER TABLE {table_name} ADD Detail8 NVARCHAR(MAX);
                    ALTER TABLE {table_name} ADD Detail9 NVARCHAR(MAX);
                    ALTER TABLE {table_name} ADD Detail10 NVARCHAR(MAX);
                END
            END
        '''
        self.execute(query)

    def ensure_chat_log_table_exists(self, table_name="EAPPDocument_AI_ChatLog"):
        """채팅 수정 이력을 저장할 테이블 생성"""
        query = f'''
            IF OBJECT_ID('{table_name}', 'U') IS NULL
            BEGIN
                CREATE TABLE {table_name} (
                    LogID INT IDENTITY(1,1) PRIMARY KEY,
                    ResultID INT,
                    UserMessage NVARCHAR(MAX),
                    BeforeDraft NVARCHAR(MAX),
                    AfterDraft NVARCHAR(MAX),
                    CreatedAt DATETIME DEFAULT GETDATE()
                )
            END
        '''
        self.execute(query)

    def insert_draft_result(self, requester_id, request_content, ref_docs, result_content, table_name="EAPPDocument_AI_Result", form_name=None, doc_summary=None, uploaded_files=None, essential_answers=None, extracted_facts=None):
        """초안 생성 결과를 테이블에 삽입"""
        # ref_docs: [{'ID': id, 'Title': title, 'Score': score}, ...] (최대 3개)
        ref1_id = ref_docs[0]['ID'] if len(ref_docs) > 0 else None
        ref1_title = ref_docs[0]['Title'] if len(ref_docs) > 0 else None
        ref1_score = ref_docs[0].get('Score') if len(ref_docs) > 0 else None
        
        ref2_id = ref_docs[1]['ID'] if len(ref_docs) > 1 else None
        ref2_title = ref_docs[1]['Title'] if len(ref_docs) > 1 else None
        ref2_score = ref_docs[1].get('Score') if len(ref_docs) > 1 else None
        
        ref3_id = ref_docs[2]['ID'] if len(ref_docs) > 2 else None
        ref3_title = ref_docs[2]['Title'] if len(ref_docs) > 2 else None
        ref3_score = ref_docs[2].get('Score') if len(ref_docs) > 2 else None

        # 리스트/딕셔너리 데이터 JSON 변환
        uploaded_files_str = json.dumps(uploaded_files, ensure_ascii=False) if isinstance(uploaded_files, (list, dict)) else uploaded_files
        essential_answers_str = json.dumps(essential_answers, ensure_ascii=False) if isinstance(essential_answers, (list, dict)) else essential_answers

        # 2단계 상세 답변을 Detail1 ~ Detail10 컬럼에 할당
        essential_items = list(essential_answers.items()) if isinstance(essential_answers, dict) else []
        details = []
        for i in range(10):
            if i < len(essential_items):
                key, val = essential_items[i]
                details.append(f"{key}: {val}" if val else f"{key}: (미입력)")
            else:
                details.append(None)

        query = f'''
            INSERT INTO {table_name} (
                RequesterID, FormName, DocSummary, UploadedFiles, EssentialAnswers, ExtractedFacts,
                Detail1, Detail2, Detail3, Detail4, Detail5, Detail6, Detail7, Detail8, Detail9, Detail10,
                RequestContent, 
                RefDocID1, RefDocTitle1, RefDocScore1,
                RefDocID2, RefDocTitle2, RefDocScore2,
                RefDocID3, RefDocTitle3, RefDocScore3,
                ResultContent
            ) 
            OUTPUT INSERTED.No
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        '''
        params = (
            requester_id, form_name, doc_summary, uploaded_files_str, essential_answers_str, extracted_facts,
            details[0], details[1], details[2], details[3], details[4], details[5], details[6], details[7], details[8], details[9],
            request_content,
            ref1_id, ref1_title, ref1_score,
            ref2_id, ref2_title, ref2_score,
            ref3_id, ref3_title, ref3_score,
            result_content
        )
        
        cursor = self.conn.cursor()
        cursor.execute(query, params)
        inserted_id = cursor.fetchone()[0]
        self.conn.commit()
        return inserted_id

    def insert_chat_log(self, result_id, user_message, before_draft, after_draft, table_name="EAPPDocument_AI_ChatLog"):
        """채팅 이력 저장"""
        query = f'''
            INSERT INTO {table_name} (
                ResultID, UserMessage, BeforeDraft, AfterDraft
            ) VALUES (?, ?, ?, ?)
        '''
        params = (result_id, user_message, before_draft, after_draft)
        self.execute(query, params)
