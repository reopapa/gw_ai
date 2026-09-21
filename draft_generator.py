import sys
import os
from config import DB_CONFIG_A, DB_CONFIG_B, GEMINI_API_KEY, GEMINI_MODEL, TABLE_AI, COHERE_API_KEY
from database import DatabaseManager
from processor import Processor

def main():
    if len(sys.argv) < 2:
        print("사용법: python draft_generator.py <사용자_사번>")
        print("예시: python draft_generator.py 20190790")
        return

    user_id = sys.argv[1]
    
    print(f"[사용자 사번] {user_id}\n")

    # 1. 초기화
    db_a = DatabaseManager(DB_CONFIG_A)
    db_b = DatabaseManager(DB_CONFIG_B)
    ai_processor = Processor(GEMINI_API_KEY, GEMINI_MODEL, COHERE_API_KEY)

    # 2. 양식 입력 받기
    form_name = input("작성하실 결재양식을 입력해주세요 (예: 기안, 구매품의, 휴가신청 등): ").strip()
    if not form_name:
        form_name = "기안"
        print(f"입력값이 없어 기본값 '{form_name}'(으)로 진행합니다.")

    doc_summary = input("작성하실 문서의 대략적인 내용을 간단히 입력해주세요 (예: 8월 노트북 구매 건): ").strip()

    attachment_path = input("참고할 첨부파일이나 폴더 경로가 있다면 입력해주세요 (없으면 엔터): ").strip()
    attachments = []
    attachment_names = []
    
    if attachment_path and os.path.exists(attachment_path):
        print("첨부 자료를 구글 서버로 업로드하여 분석을 준비 중입니다...")
        if os.path.isfile(attachment_path):
            file_obj = ai_processor.upload_file(attachment_path)
            if file_obj:
                attachments.append(file_obj)
                attachment_names.append(os.path.basename(attachment_path))
        elif os.path.isdir(attachment_path):
            for filename in os.listdir(attachment_path):
                filepath = os.path.join(attachment_path, filename)
                if os.path.isfile(filepath):
                    file_obj = ai_processor.upload_file(filepath)
                    if file_obj:
                        attachments.append(file_obj)
                        attachment_names.append(filename)

    enriched_summary = doc_summary
    if attachment_names:
        enriched_summary += f"\n\n[첨부 파일 목록]\n" + ", ".join(attachment_names)

    print(f"\n--- '{form_name}' 양식 작성을 위한 필수 항목 분석 중... ---")
    essential_fields = ai_processor.generate_form_questions(form_name, doc_summary=enriched_summary, attachments=attachments)
    
    print("\n아래 필수 항목에 대해 간단히 기입해주세요. (미입력 시 AI가 웹 검색 등을 통해 자동 작성합니다)")
    user_inputs = {}
    for field in essential_fields:
        val = input(f"- {field}: ").strip()
        user_inputs[field] = val
        
    user_request = f"결재양식: {form_name}\n"
    if enriched_summary:
        user_request += f"문서 요약 및 첨부자료: \n{enriched_summary}\n"
    for field, value in user_inputs.items():
        user_request += f"- {field}: {value if value else '내용 없음 (웹 검색 및 문맥 기반 자동 작성 요망)'}\n"
        
    print("\n[최종 입력 데이터]")
    print(user_request)

    try:
        # DB 연결
        db_b.connect()
        db_a.connect()

        # Step 1: EAPPDocument_AI 테이블에서 권한에 맞는 문서 목록 가져오기
        print(f"\n--- 1단계: 유사한 기안 문서 검색 (EAPPDocument_AI, 사용자: {user_id}) ---")
        
        query_b = f"""
        SELECT DISTINCT
            DOC.ID,
            DOC.Title,
            DOC.WriterID,
            DOC.Writer,
            DOC.DepartID,
            DOC.DeptName1,
            DOC.RegDate,
            DOC.Keywords,
            DOC.Summary,
            DOC.FormName,
            DOC.EACode
        FROM 
            {TABLE_AI} DOC
        LEFT JOIN 
            [gw(new)].[crewcloud_company].[dbo].[EAPPProgress] PROG 
            ON DOC.ID = PROG.documentid
        INNER JOIN 
            [gw(new)].[crewcloud_company].[dbo].[Organization_Users] U 
            ON U.userid = ? AND U.enabled = 1
        INNER JOIN 
            [gw(new)].[crewcloud_company].[dbo].[Organization_BelongToDepartment] B 
            ON U.userno = B.UserNo
        INNER JOIN 
            [gw(new)].[crewcloud_company].[dbo].[Organization_Departments] D 
            ON B.DepartNo = D.DepartNo AND D.Enabled = 1
        WHERE 
            DOC.IsDelete = 0 
            AND DOC.RegDate >= DATEADD(year, -3, GETDATE())
            AND (
                DOC.WriterID = U.userid
                OR PROG.managerid = U.userid
                OR PROG.departid = CAST(B.DepartNo AS NVARCHAR(50))
            )
        """
        
        try:
            columns, rows = db_b.fetch_all_with_params(query_b, (user_id,))
        except Exception as e:
            print(f"[ERROR] 중간 테이블({TABLE_AI}) 조회 실패: {e}")
            return
            
        if not rows:
            print("해당 사용자의 권한으로 조회 가능한 기안 데이터가 없습니다. 표준 양식으로 초안을 작성합니다.")
            documents = []
        else:
            documents = []
            for row in rows:
                data = dict(zip(columns, row))
                documents.append(data)
                
            print(f"권한 확인된 총 {len(documents)}개의 문서 중 1차로 유사한 Top 25를 찾습니다...")
        
        # [1-1단계] AI를 통한 1차 유사도 분석 및 Top 25 추출
        search_query = user_request
        if documents:
            search_query, top25_ids = ai_processor.find_top_25_similar(user_request, documents, form_name=form_name)
        else:
            top25_ids = []
        
        if not top25_ids:
            print("1차 유사한 문서를 찾을 수 없거나 데이터가 없어, 표준 양식으로 초안을 작성합니다.\n")
            top3_results = []
        else:
            print(f"1차 선정된 Top 25 문서 ID: {top25_ids}\n")
        
            # [1-2단계] 리랭커(Re-ranker) API를 통해 Top 25 중 최종 Top 3 추출
            top25_documents = [d for d in documents if d['ID'] in top25_ids]
            
            print(f"리랭커(Re-ranker) API를 통해 가장 우수한 Top 3 문서를 최종 선정합니다... (정제된 검색어: '{search_query}')")
            top3_results = ai_processor.rerank_to_top_3(search_query, top25_documents)
        
        top3_ids = [item['ID'] for item in top3_results]
        if top3_results:
            print(f"최종 선정된 Top 3 문서 ID 및 점수: {top3_results}\n")
        else:
            print("기준 점수를 넘는 유사한 문서를 찾을 수 없어, 표준 양식으로만 초안을 작성합니다.\n")

        # Step 2: 원본 서버A에서 Top 3 원본 문서 내용 가져오기 및 초안 작성
        print("--- 2단계: 원본 서버(A)에서 내용 확인 및 기안 초안 작성 ---")
        
        top3_contents = []
        ref_docs = []
        
        if top3_ids:
            placeholders = ", ".join(["?"] * len(top3_ids))
            query_a = f"SELECT ID, Title, Content FROM EAPPDocument WHERE ID IN ({placeholders})"
            
            columns_a, rows_a = db_a.fetch_all_with_params(query_a, top3_ids)
            
            if rows_a:
                doc_dict = {}
                for row_a in rows_a:
                    data_a = dict(zip(columns_a, row_a))
                    doc_dict[data_a['ID']] = data_a

                for result_item in top3_results:
                    doc_id = result_item['ID']
                    if doc_id in doc_dict:
                        data_a = doc_dict[doc_id]
                        score = result_item['Score']
                        print(f"참조 문서 확인: [ID {data_a['ID']}] {data_a['Title']} (Score: {score:.4f})")
                        md_content = ai_processor.html_to_markdown(data_a['Content'])
                        top3_contents.append(md_content)
                        ref_docs.append({'ID': data_a['ID'], 'Title': data_a['Title'], 'Score': score})
            else:
                print("[WARNING] 원본 서버에서 해당 ID의 문서를 찾을 수 없습니다.")

        print("\nAI가 기안 초안을 작성 중입니다... (웹 검색 및 첨부파일 보강 포함)\n")
        # 사용자의 요청에 따라 웹 검색은 항시 True로 사용하여 미입력 내용을 보강합니다.
        draft_result = ai_processor.generate_draft(user_request, top3_contents, use_web_search=True, attachments=attachments)
        
        print("="*60)
        print("[AI 기안 초안 작성 결과]")
        print("="*60)
        print(draft_result)
        print("="*60)
        
        cleaned_draft = draft_result.replace("```html", "").replace("```", "").strip()
        
        print("--- 3단계: 결과를 데이터베이스에 저장 ---")
        db_b.ensure_result_table_exists()
        db_b.insert_draft_result(user_id, user_request, ref_docs, cleaned_draft)
        
        print("\n[안내] 작성된 기안 초안 결과가 테이블(EAPPDocument_AI_Result)에 성공적으로 저장되었습니다.")

    except Exception as e:
        print(f"[FATAL ERROR] {e}")
    finally:
        db_a.close()
        db_b.close()

if __name__ == "__main__":
    main()
