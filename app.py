import streamlit as st
import os
import time
import json
import concurrent.futures
import tempfile
import uuid
from config import DB_CONFIG_A, DB_CONFIG_B, GEMINI_API_KEY, GEMINI_MODEL, COHERE_API_KEY, TABLE_AI, OPENAI_MODEL, OPENAI_API_KEY
from database import DatabaseManager
from processor import Processor
from datetime import datetime

# 페이지 설정
st.set_page_config(page_title="AI 기안 초안 생성기", layout="wide")

# 세션 상태 초기화
if "step" not in st.session_state:
    st.session_state.step = 1
if "essential_fields" not in st.session_state:
    st.session_state.essential_fields = []
if "uploaded_gemini_files" not in st.session_state:
    st.session_state.uploaded_gemini_files = []
if "uploaded_gemini_file_names" not in st.session_state:
    st.session_state.uploaded_gemini_file_names = []
if "uploaded_filenames" not in st.session_state:
    st.session_state.uploaded_filenames = []
if "enriched_summary" not in st.session_state:
    st.session_state.enriched_summary = ""

# 프로세서 인스턴스 (한번만 로드)
@st.cache_resource
def get_processor_v13():
    return Processor(GEMINI_API_KEY, GEMINI_MODEL, COHERE_API_KEY, openai_api_key=OPENAI_API_KEY)

@st.cache_resource
def get_db_a():
    db = DatabaseManager(DB_CONFIG_A)
    db.connect()
    return db

@st.cache_resource
def get_db_b():
    db = DatabaseManager(DB_CONFIG_B)
    db.connect()
    return db

def safe_db_fetch(db, query_fn, *args, **kwargs):
    """DB 연결이 끊긴 경우 자동 재연결 후 재시도"""
    try:
        return query_fn(*args, **kwargs)
    except Exception:
        try:
            db.connect()
            return query_fn(*args, **kwargs)
        except Exception as e:
            raise e

processor = get_processor_v13()
db_a = get_db_a()
db_b = get_db_b()

st.title("📄 AI 기안/품의서 초안 생성 도우미 (내부테스트용)")

# ================================
# STEP 1: 기본 정보 입력
# ================================
if st.session_state.step == 1:
    st.header("1단계: 기본 정보 입력")
    
    user_id = st.text_input("사용자 사번 (예: 20190790)", value=st.session_state.get("user_id", ""))
    
    form_options = ["기안", "구매품의", "휴가신청", "보고서", "지출결의", "공지", "직접입력"]
    default_form_index = 0
    if "form_option_selected" in st.session_state and st.session_state.form_option_selected in form_options:
        default_form_index = form_options.index(st.session_state.form_option_selected)
        
    form_option = st.selectbox(
        "결재 양식 선택",
        form_options,
        index=default_form_index,
        key="form_option_selectbox"
    )
    
    if form_option == "직접입력":
        custom_form_name = st.text_input(
            "결재 양식명 직접 입력",
            value=st.session_state.get("custom_form_name", ""),
            placeholder="예: 프로젝트 제안서"
        )
    else:
        custom_form_name = ""
        
    st.markdown("##### 문서 대략적 내용")
    st.caption("💡 작성하고자 하는 문서의 목적, 주요 배경, 요청사항 등 핵심 내용을 적어주시면 AI가 더 정확한 초안을 생성합니다.")
    doc_summary = st.text_area(
        "문서 내용 요약",
        value=st.session_state.get("doc_summary", ""),
        placeholder="예: 2026년 하반기 신규 입사자의 업무 환경 조성을 위해 최신 사양 노트북 구매를 위한 품의",
        height=120,
        label_visibility="collapsed"
    )
    
    st.markdown("##### 초안 생성 AI 모델 선택")
    st.caption("💡 기안서 작성에 사용할 인공지능 모델을 선택합니다.")
    draft_model_option = st.radio(
        "모델 선택",
        [f"Gemini ({GEMINI_MODEL})", f"GPT ({OPENAI_MODEL})"],
        index=0,
        horizontal=True,
        label_visibility="collapsed"
    )

    submit_btn = st.button("다음단계", type="primary", use_container_width=True)
        
    if submit_btn:
        if not user_id:
            st.error("사번을 입력해주세요.")
            st.stop()
            
        form_name = custom_form_name.strip() if form_option == "직접입력" else form_option
        if not form_name:
            st.error("결재 양식명을 입력해주세요.")
            st.stop()
            
        st.session_state.form_option_selected = form_option
        st.session_state.custom_form_name = custom_form_name
        st.session_state.user_id = user_id
        st.session_state.form_name = form_name
        st.session_state.doc_summary = doc_summary
        
        if draft_model_option.startswith("Gemini"):
            st.session_state.draft_model = GEMINI_MODEL
        else:
            st.session_state.draft_model = OPENAI_MODEL
        
        # Step 2 Logic Moved Here
        user_request = f"결재양식: {st.session_state.form_name}\n문서 요약: \n{st.session_state.doc_summary}"
        
        st.markdown("""
        <style>
        div[data-testid="stTextInput"], 
        div[data-testid="stTextArea"], 
        div[data-testid="stSelectbox"],
        div[data-testid="stFileUploader"],
        div[data-testid="stCheckbox"],
        div[data-testid="stRadio"],
        button[kind="primary"],
        button[kind="secondary"] {
            opacity: 0.5;
            pointer-events: none;
        }
        </style>
        """, unsafe_allow_html=True)
        
        with st.status("🚀 다음 단계로 넘어가는 중... (유사 문서 검색)", expanded=True) as status:
            st.write("AI가 회사 내부 과거 유사 문서를 검색하고 있습니다...")
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
                columns_b, rows_b = db_b.fetch_all_with_params(query_b, (st.session_state.user_id,))
            except Exception as e:
                st.error(f"DB 조회 실패: {e}")
                st.stop()
                
            documents = []
            if rows_b:
                for row in rows_b:
                    data = dict(zip(columns_b, row))
                    documents.append(data)
            
            search_query = user_request
            top3_results = []
            if documents:
                search_query, top25_ids = processor.find_top_25_similar(user_request, documents, form_name=st.session_state.form_name)
                top25_documents = [d for d in documents if d['ID'] in top25_ids]
                if top25_documents:
                    top3_results = processor.rerank_to_top_3(search_query, top25_documents)
                    
            st.session_state.top3_results = top3_results
            
            top3_contents = {}
            top3_html_contents = {}
            if top3_results:
                top3_ids = [res['ID'] for res in top3_results]
                placeholders = ", ".join(["?"] * len(top3_ids))
                query_a = f"SELECT ID, Title, Content FROM EAPPDocument WHERE ID IN ({placeholders})"
                columns_a, rows_a = db_a.fetch_all_with_params(query_a, top3_ids)
                if rows_a:
                    doc_dict = {}
                    for row_a in rows_a:
                        data_a = dict(zip(columns_a, row_a))
                        doc_dict[str(data_a['ID'])] = data_a

                    for result_item in top3_results:
                        doc_id = str(result_item['ID'])
                        if doc_id in doc_dict:
                            data_a = doc_dict[doc_id]
                            md_content = processor.html_to_markdown(data_a['Content'])
                            top3_contents[doc_id] = md_content
                            top3_html_contents[doc_id] = data_a['Content']
                            
            st.session_state.top3_contents = top3_contents
            st.session_state.top3_html_contents = top3_html_contents
            
            status.update(label="검색 완료! 다음 단계로 이동합니다.", state="complete", expanded=False)

        st.session_state.step = 2
        st.rerun()

# ================================
# STEP 2: 유사 문서 참고 및 파일 첨부
# ================================
elif st.session_state.step == 2:
    st.header("2단계: 참고 문서 선택 및 첨부파일")
    


    top3_results = st.session_state.get("top3_results", [])
    selected_doc_ids = []
    
    st.markdown("##### 과거 유사 결재 문서")
    if top3_results:
        st.info("💡 과거 작성된 유사 문서 목록입니다. 참고할 문서를 선택해주세요.")
        for res in top3_results:
            doc_id = str(res['ID'])
            
            col1, col2 = st.columns([0.75, 0.25])
            with col1:
                is_checked = st.checkbox(f"[{doc_id}] {res['Title']}", value=True, key=f"doc_{doc_id}")
            with col2:
                with st.popover("🔍 미리보기"):
                    col_top1, col_top2 = st.columns([0.9, 0.1])
                    with col_top1:
                        st.markdown(f"**[{doc_id}] {res['Title']}**")
                    with col_top2:
                        st.button("❌", key=f"close_btn_{doc_id}", help="닫기")
                        
                    st.markdown("""<style>div[data-testid="stPopoverBody"] { min-width: 700px !important; max-width: 90vw !important; }</style>""", unsafe_allow_html=True)
                    preview_url = f"https://gw.taekyung.co.kr/Eapp/UI/EAView?docid={doc_id}&lType=1&lState=3&cPage=1&sType=&sKeyword=&WT=&ST=regdate^"
                    
                    if doc_id in st.session_state.get('top3_html_contents', {}):
                        st.components.v1.html(st.session_state.top3_html_contents[doc_id], height=500, scrolling=True)
                    elif doc_id in st.session_state.top3_contents:
                        st.markdown(st.session_state.top3_contents[doc_id])
                    else:
                        st.info("본문 내용을 불러올 수 없습니다.")
                        
                    st.markdown(f"👉 **[원문 그룹웨어에서 열기]({preview_url})**")
                        
            if is_checked:
                selected_doc_ids.append(doc_id)
        
        draft_method = st.radio(
            "초안 작성 방식",
            ["유사 문서 기반으로만 작성 (웹 검색 제외)", "웹 검색을 활용하여 작성 (선택한 문서 + 웹 검색)"],
            index=0,
            key="draft_method_radio"
        )
        use_web_search = (draft_method == "웹 검색을 활용하여 작성 (선택한 문서 + 웹 검색)")
    else:
        st.warning("⚠️ 유사한 과거 결재 문서가 없습니다. AI 웹 검색을 통해 초안을 작성합니다.")
        use_web_search = True
        
    st.markdown("##### 참고 첨부파일 (선택)")
    st.markdown("PDF, 엑셀, 워드 등 참고할 문서가 있다면 업로드해주세요.")
    uploaded_files = st.file_uploader("파일 업로드", accept_multiple_files=True, key="file_uploader_step2")
        
    col1, col2 = st.columns(2)
    with col1:
        if st.button("이전단계", use_container_width=True):
            st.session_state.step = 1
            st.rerun()
            
    with col2:
        if st.button("다음단계", type="primary", use_container_width=True):
            if top3_results and not selected_doc_ids and not use_web_search and not uploaded_files:
                st.error("참고할 문서를 하나 이상 선택하시거나, 웹 검색을 활용하는 방식을 선택해주세요.")
                st.stop()
                
            gemini_files = []
            gemini_file_names = []
            filenames = []
            
            if uploaded_files:
                upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
                os.makedirs(upload_dir, exist_ok=True)
                
                progress_bar = st.progress(0, text="첨부파일 처리 중... (0%)")
                total_files = len(uploaded_files)
                completed_files = 0
                
                def process_single_file(uf):
                    ext = os.path.splitext(uf.name)[1].lower()
                    safe_ascii_name = f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}{ext}"
                    save_path = os.path.join(upload_dir, safe_ascii_name)
                    file_bytes = uf.getvalue()
                    
                    with open(save_path, "wb") as f:
                        f.write(file_bytes)
                    
                    file_obj = None
                    err_msg = None
                    try:
                        file_obj = processor.upload_file(save_path, wait_active=True)
                    except Exception as upload_err:
                        err_msg = f"❌ [{uf.name}] 파일 처리 중 오류: {upload_err}"
                    finally:
                        if os.path.exists(save_path):
                            try:
                                os.remove(save_path)
                            except Exception:
                                pass
                    return uf.name, file_obj, err_msg, file_bytes, ext
                
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    futures = {executor.submit(process_single_file, uf): uf for uf in uploaded_files}
                    has_error = False
                    file_bytes_list = []
                    for future in concurrent.futures.as_completed(futures):
                        uf_name, f_obj, err, f_bytes, f_ext = future.result()
                        completed_files += 1
                        progress_bar.progress(completed_files / total_files, text=f"첨부파일 처리 중... ({completed_files}/{total_files})")
                        
                        if err:
                            st.error(err)
                            has_error = True
                        elif f_obj:
                            gemini_files.append(f_obj)
                            if hasattr(f_obj, 'name'):
                                gemini_file_names.append(f_obj.name)
                            filenames.append(uf_name)
                            file_bytes_list.append({"name": uf_name, "bytes": f_bytes, "ext": f_ext})
                        else:
                            st.warning(f"⚠️ [{uf_name}] 첨부파일 업로드에 실패하였습니다.")
                            has_error = True
                            
                if has_error:
                    st.error("❌ 일부 첨부파일 처리 중 오류가 발생하여 다음 단계로 넘어갈 수 없습니다. 오류를 확인해주세요.")
                    st.stop()
                else:
                    progress_bar.progress(1.0, text="✅ 첨부파일 처리 완료!")
                    time.sleep(0.5)
                                
            st.session_state.uploaded_gemini_files = gemini_files
            st.session_state.uploaded_gemini_file_names = gemini_file_names
            st.session_state.uploaded_filenames = filenames
            st.session_state.uploaded_file_bytes = file_bytes_list if uploaded_files else []

                
            st.session_state.selected_doc_ids = selected_doc_ids
            st.session_state.use_web_search = use_web_search
            
            st.markdown("""
            <style>
            div[data-testid="stTextInput"], 
            div[data-testid="stTextArea"], 
            div[data-testid="stSelectbox"],
            div[data-testid="stFileUploader"],
            div[data-testid="stCheckbox"],
            div[data-testid="stRadio"],
            button[kind="primary"],
            button[kind="secondary"] {
                opacity: 0.5;
                pointer-events: none;
            }
            </style>
            """, unsafe_allow_html=True)
            
            with st.status("🚀 핵심 기안 요소 설계 준비 중...", expanded=True) as status:
                # Step 3 logic moved here
                user_request = f"결재양식: {st.session_state.form_name}\n"
                if st.session_state.doc_summary:
                    user_request += f"문서 요약 및 첨부자료: \n{st.session_state.doc_summary}\n"
                
                files_to_process = st.session_state.get("uploaded_gemini_files", [])
                has_files = len(files_to_process) > 0
                
                if has_files:
                    filenames_str = ", ".join(st.session_state.get('uploaded_filenames', []))
                    st.write(f"AI가 첨부파일({filenames_str})의 상세 내역을 정밀 판독하고 있습니다...")
                    extracted_facts = processor.extract_attachment_facts(files_to_process)
                    st.session_state.extracted_facts = extracted_facts
                
                extracted_facts = st.session_state.get("extracted_facts")
                
                st.write("AI가 완벽한 기안 작성을 위한 필수 체크리스트를 도출하고 있습니다...")
                top3_contents_list = []
                if "top3_contents" in st.session_state and "selected_doc_ids" in st.session_state:
                    for doc_id in st.session_state.selected_doc_ids:
                        if doc_id in st.session_state.top3_contents:
                            top3_contents_list.append(st.session_state.top3_contents[doc_id])
                            
                checklist_json_str = processor.generate_essential_checklist(
                    user_request, 
                    top3_contents_list, 
                    extracted_facts=extracted_facts,
                    attachments=files_to_process if has_files else None,
                    file_bytes_list=st.session_state.get("uploaded_file_bytes") if has_files else None,
                    target_model=st.session_state.get("draft_model", "gemini-3.8-flash")
                )
                
                try:
                    clean_json = checklist_json_str.strip()
                    start_idx = clean_json.find('[')
                    end_idx = clean_json.rfind(']')
                    
                    if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
                        clean_json = clean_json[start_idx:end_idx+1]
                    else:
                        raise ValueError("JSON 배열 대괄호([, ])를 찾을 수 없습니다.")
                        
                    checklist_items = json.loads(clean_json)
                    if not checklist_items:
                        st.warning("⚠️ AI가 체크리스트를 생성하지 못했습니다. 기본 항목으로 진행합니다.")
                        checklist_items = [
                            {"item": "작성 목적", "value": "", "source": "기본 항목"},
                            {"item": "상세 내용", "value": "", "source": "기본 항목"},
                            {"item": "기대 효과", "value": "", "source": "기본 항목"}
                        ]
                except Exception as e:
                    print(f"[ERROR] JSON Parsing Error: {e}")
                    print(f"[DEBUG] 원본 텍스트: {checklist_json_str}")
                    st.warning("⚠️ 체크리스트 파싱 중 오류가 발생했습니다. 기본 항목으로 진행합니다.")
                    checklist_items = [
                        {"item": "작성 목적", "value": "", "source": "기본 항목"},
                        {"item": "상세 내용", "value": "", "source": "기본 항목"},
                        {"item": "기대 효과", "value": "", "source": "기본 항목"}
                    ]
                    
                st.session_state.checklist_items = checklist_items
                status.update(label="체크리스트 도출 완료! 다음 단계로 이동합니다.", state="complete", expanded=False)

            st.session_state.step = 3
            st.rerun()

# ================================
# STEP 3: 필수 체크리스트 작성
# ================================
elif st.session_state.step == 3:
    st.header("3단계: 핵심 기안 요소 설계 (추가 및 제외)")
    

    st.info("💡 AI가 파악한 핵심 기안 요소입니다. 미리 채워진(Pre-fill) 내용을 검증해주시고, 빈칸으로 표시된 누락 정보는 추가 입력하시거나 비워두시면 AI가 문맥에 맞게 자동 작성(Auto-fill)합니다.")
    
    def process_step3_add_custom():
        new_item_name = st.session_state.get("custom_item_name", "").strip()
        new_item_val = st.session_state.get("custom_item_val", "").strip()
        
        if new_item_name:
            if "checklist_items" in st.session_state:
                st.session_state.checklist_items.append({
                    "item": new_item_name,
                    "source": "사용자 맞춤 직접 추가",
                    "value": new_item_val
                })
            # 텍스트 필드 비우기
            st.session_state.custom_item_name = ""
            st.session_state.custom_item_val = ""
            # 스크롤 플래그 켜기
            st.session_state.scroll_to_bottom = True
            
    with st.popover("➕ 사용자 맞춤 항목 추가", use_container_width=False):
        st.markdown("**기안서에 꼭 포함되어야 할 필수 항목을 직접 추가하세요.**")
        st.text_input("항목명 (예: 리스크 대응 방안)", key="custom_item_name")
        st.text_input("답변/가이드 (예: 일정 지연 시 외주 인력 투입)", key="custom_item_val")
        
        st.button("목록에 추가하기", type="primary", use_container_width=True, on_click=process_step3_add_custom)
    
    checklist_items = st.session_state.get("checklist_items", [])
    
    # 폼 생성
    with st.form("checklist_form"):
        for i, item_obj in enumerate(checklist_items):
            item_name = item_obj.get("item", f"항목 {i+1}")
            item_source = item_obj.get("source", "")
            item_value = item_obj.get("value", "")
            
            if f"chk_{i}" not in st.session_state:
                st.session_state[f"chk_{i}"] = item_value
                
            # 체크박스로 포함 여부 선택
            include_key = f"include_{i}"
            st.checkbox(f"📌 {item_name}", value=True, key=include_key)
            
            # 들여쓰기를 위해 컬럼 분리
            col_spacer, col_content = st.columns([0.03, 0.97])
            with col_content:
                st.text_input("답변 (비워두면 자동 작성)", key=f"chk_{i}", label_visibility="collapsed")
                
                if item_source:
                    st.caption(f"💡 도출 근거: {item_source}")
            
            st.write("") # 간격 띄우기
                
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        with col1:
            prev_btn = st.form_submit_button("이전단계", use_container_width=True)
        with col2:
            next_btn = st.form_submit_button("다음단계 (초안 생성)", type="primary", use_container_width=True)
            
        st.markdown("<div id='step3-bottom'></div>", unsafe_allow_html=True)
        if st.session_state.get("scroll_to_bottom"):
            scroll_js = """
            <script>
                setTimeout(function() {
                    var el = window.parent.document.getElementById('step3-bottom');
                    if(el) {
                        el.scrollIntoView({behavior: 'smooth', block: 'end'});
                    }
                }, 300);
            </script>
            """
            st.components.v1.html(scroll_js, height=0)
            st.session_state.scroll_to_bottom = False
            
    if prev_btn:
        st.session_state.step = 2
        st.rerun()
        
    if next_btn:
        st.markdown("""
        <style>
        div[data-testid="stTextInput"], 
        div[data-testid="stTextArea"], 
        div[data-testid="stSelectbox"],
        div[data-testid="stFileUploader"],
        div[data-testid="stCheckbox"],
        div[data-testid="stRadio"],
        button[kind="primary"],
        button[kind="secondary"] {
            opacity: 0.5;
            pointer-events: none;
        }
        </style>
        """, unsafe_allow_html=True)
        
        with st.status("🚀 기안서 초안 작성 중...", expanded=True) as status:
            final_answers = {}
            final_sources = {}
            excluded_items = []
            for idx, item_obj in enumerate(st.session_state.get("checklist_items", [])):
                i_name = item_obj.get("item", f"항목 {idx+1}")
                if st.session_state.get(f"include_{idx}", True):
                    final_answers[i_name] = st.session_state.get(f"chk_{idx}", "")
                    final_sources[i_name] = item_obj.get("source", "")
                else:
                    excluded_items.append(i_name)
                    
            st.session_state.essential_answers = final_answers
            st.session_state.essential_sources = final_sources
            st.session_state.excluded_items = excluded_items
            
            user_request = f"결재양식: {st.session_state.form_name}\n"
            if st.session_state.doc_summary:
                user_request += f"문서 요약 및 첨부자료: \n{st.session_state.doc_summary}\n"
                
            extracted_facts = st.session_state.get("extracted_facts")
            if extracted_facts:
                user_request += f"\n\n[초격차 중요: 첨부파일 정밀 판독 결과 (이 팩트 데이터만을 절대적으로 신뢰할 것)]\n{extracted_facts}\n"
                
            st.write("AI가 팩트 데이터와 문맥을 조합하여 초안을 작성하고 있습니다. (약 30초~1분 소요)...")
            # 선택된 문서 컨텐츠 조합
            top3_contents_list = []
            if "top3_contents" in st.session_state and "selected_doc_ids" in st.session_state:
                for doc_id in st.session_state.selected_doc_ids:
                    if doc_id in st.session_state.top3_contents:
                        top3_contents_list.append(st.session_state.top3_contents[doc_id])
            
            files_to_process = st.session_state.get("uploaded_gemini_files", [])
            has_files = len(files_to_process) > 0
            
            # 초안 생성
            use_web_search = st.session_state.get("use_web_search", False)
            draft_result = processor.generate_draft(
                user_request, 
                top3_contents_list, 
                use_web_search=use_web_search, 
                extracted_facts=extracted_facts if has_files else None,
                attachments=files_to_process if has_files else None,
                file_bytes_list=st.session_state.get("uploaded_file_bytes") if has_files else None,
                essential_answers=st.session_state.get("essential_answers"),
                excluded_items=st.session_state.get("excluded_items"),
                target_model=st.session_state.get("draft_model", "gemini-3.8-flash")
            )
            
            # DB 저장
            try:
                db_b.ensure_result_table_exists()
                db_b.ensure_chat_log_table_exists()
                inserted_id = db_b.insert_draft_result(
                    requester_id=st.session_state.user_id,
                    request_content=user_request,
                    ref_docs=st.session_state.get("top3_results", []),
                    result_content=draft_result,
                    form_name=st.session_state.get("form_name"),
                    doc_summary=st.session_state.get("doc_summary"),
                    uploaded_files=st.session_state.get("uploaded_filenames", []),
                    essential_answers=st.session_state.get("essential_answers", {}),
                    extracted_facts=extracted_facts
                )
                st.session_state.draft_result_id = inserted_id
                st.session_state.extracted_facts = extracted_facts
                st.success("🎉 생성된 기안 초안이 데이터베이스에 성공적으로 저장되었습니다!")
            except Exception as e:
                st.error(f"데이터베이스 저장 중 오류가 발생했습니다: {e}")

            st.session_state.draft_result = draft_result
            status.update(label="초안 작성 완료! 결과 화면으로 이동합니다.", state="complete", expanded=False)
            
        st.session_state.step = 4
        st.rerun()

# ================================
# STEP 4: 기안 초안 생성 및 저장
# ================================
elif st.session_state.step == 4:
    st.header("4단계: 기안 초안 생성 결과")
    


    # 결과 출력
    st.markdown("### 📝 단락별 내용 확인 및 수정")
    st.info("💡 우측 상단의 **'📋 전체 복사'** 버튼을 누르면 기안서 전체가 복사됩니다. 단락을 수정하려면 각 단락 하단의 **[💬 Comment]** 버튼을 눌러 지시사항을 남기세요.")
    
    copy_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <style>
        body {{ margin:0; padding:0; overflow:hidden; }}
        .copy-btn {{
            width: 100%;
            height: 40px;
            background-color: #ffffff;
            color: #31333F;
            border: 1px solid #d4d4d8;
            border-radius: 8px;
            cursor: pointer;
            font-size: 15px;
            font-weight: 500;
        }}
        .copy-btn:hover {{ border-color: #ff4b4b; color: #ff4b4b; }}
    </style>
    </head>
    <body>
        <button class="copy-btn" onclick="copyRichText()">📋 전체 복사</button>
        <div id="content" style="display:none; position:absolute; left:-9999px;">
            <div style="max-width: 970px; width: 100%; margin: 0 auto;">
                {st.session_state.draft_result}
            </div>
        </div>
        <script>
            function copyRichText() {{
                var elm = document.getElementById("content");
                elm.style.display = "block";
                var selection = window.getSelection();
                var range = document.createRange();
                range.selectNodeContents(elm);
                selection.removeAllRanges();
                selection.addRange(range);
                
                try {{
                    var successful = document.execCommand('copy');
                    if (successful) {{
                        alert('✅ 전체 기안서가 복사되었습니다!');
                    }} else {{
                        alert('복사 권한이 없습니다.');
                    }}
                }} catch (err) {{
                    alert('복사를 지원하지 않는 브라우저입니다.');
                }}
                selection.removeAllRanges();
                elm.style.display = "none";
            }}
        </script>
    </body>
    </html>
    """
    
    sections = processor.split_html_into_sections(st.session_state.draft_result)
    st.session_state.draft_sections_count = len(sections)
    
    def process_step4_edit():
        edit_instructions = []
        for i in range(st.session_state.draft_sections_count):
            instr = st.session_state.get(f"edit_sec_{i}", "")
            edit_instructions.append(instr)
            
        if any(instr.strip() for instr in edit_instructions):
            with st.spinner("선택된 단락들을 AI가 수정하고 있습니다 (병렬 처리 중)..."):
                import concurrent.futures
                extracted_facts = st.session_state.get("extracted_facts")
                attachments = st.session_state.get("uploaded_gemini_files")
                full_draft = st.session_state.draft_result
                current_sections = processor.split_html_into_sections(full_draft)
                
                def process_section(idx, sec_html, instr):
                    if not instr.strip():
                        return sec_html
                    return processor.refine_draft_section(
                        sec_html, instr, full_draft, 
                        extracted_facts=extracted_facts, 
                        attachments=attachments, 
                        file_bytes_list=st.session_state.get("uploaded_file_bytes"),
                        target_model=st.session_state.get("draft_model", "gemini-3.8-flash")
                    )
                
                updated_sections = [None] * len(current_sections)
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                    futures = {executor.submit(process_section, i, current_sections[i], edit_instructions[i]): i for i in range(len(current_sections))}
                    for future in concurrent.futures.as_completed(futures):
                        idx = futures[future]
                        try:
                            updated_sections[idx] = future.result()
                        except Exception as e:
                            print(f"[ERROR] 단락 {idx+1} 수정 중 예외: {e}")
                            updated_sections[idx] = current_sections[idx]
                
                new_draft = "".join(updated_sections)
                
                if "draft_result_id" in st.session_state:
                    try:
                        combined_msg = "\n".join([f"[단락 {i+1}] {instr}" for i, instr in enumerate(edit_instructions) if instr.strip()])
                        db_b.insert_chat_log(
                            result_id=st.session_state.draft_result_id,
                            user_message=combined_msg,
                            before_draft=full_draft,
                            after_draft=new_draft
                        )
                    except Exception as e:
                        print(f"[ERROR] 채팅 이력 DB 저장 오류: {e}")
                        
                st.session_state.draft_result = new_draft
                
                # 수정 반영 후 입력창 초기화
                for i in range(st.session_state.draft_sections_count):
                    if f"edit_sec_{i}" in st.session_state:
                        st.session_state[f"edit_sec_{i}"] = ""

    with st.form("section_edit_form"):
        # 상단 우측에 버튼 2개 나란히 배치
        col_blank, col_copy, col_submit = st.columns([0.7, 0.15, 0.15])
        with col_copy:
            st.components.v1.html(copy_html, height=45)
        with col_submit:
            st.form_submit_button("최종 수정 반영", type="primary", use_container_width=True, on_click=process_step4_edit)
            
        st.write("") # 간격
        
        import re
        def extract_text(html_str):
            return re.sub(r'<[^>]+>', ' ', html_str)
            
        for i, sec in enumerate(sections):
            with st.container(border=True):
                # 가로 길이 제한 적용
                wrapped_sec = f'<div style="max-width: 970px; margin: 0 auto;">\n{sec}\n</div>'
                st.markdown(wrapped_sec, unsafe_allow_html=True)
                
                # 도출 근거 매칭 및 표시
                h_tags = re.findall(r'<h[1-6][^>]*>(.*?)</h[1-6]>', sec, re.IGNORECASE)
                sec_header_text = " ".join(h_tags).lower() if h_tags else ""
                
                matched_sources = []
                for k, v in st.session_state.get("essential_sources", {}).items():
                    if v and v.strip() and v != "사용자 맞춤 직접 추가":
                        if k in st.session_state.get("excluded_items", []):
                            continue
                            
                        clean_k = re.sub(r'\(.*?\)', '', k)
                        words = [w for w in clean_k.replace(' 및 ', ' ').split() if len(w) >= 2]
                        
                        is_match = False
                        if sec_header_text and words:
                            match_count = sum(1 for w in words if w.lower() in sec_header_text)
                            match_ratio = match_count / len(words)
                            if match_ratio >= 0.5:
                                is_match = True
                                
                        if is_match:
                            user_ans = st.session_state.get("essential_answers", {}).get(k, "")
                            if not user_ans or not str(user_ans).strip():
                                use_web = st.session_state.get("use_web_search", False)
                                
                                # 참고 문서 제목 추출
                                top3 = st.session_state.get("top3_results", [])
                                selected_ids = st.session_state.get("selected_doc_ids", [])
                                selected_docs = [d for d in top3 if d.get('ID') in selected_ids]
                                
                                ref_docs_str = ", ".join([f"'{d.get('Title', '제목 없음')}'" for d in selected_docs])
                                ref_msg = f"사내 유사 기안서({ref_docs_str})" if ref_docs_str else ""
                                
                                if use_web:
                                    # 웹 검색 출처 추출
                                    web_sources = getattr(processor, 'last_web_sources', [])
                                    web_msg = ""
                                    if web_sources:
                                        sites = [f"<a href='{s.get('uri', '')}' target='_blank' style='color:#0284c7;text-decoration:underline;'>{s.get('title', '웹문서')}</a>" for s in web_sources[:3]]
                                        web_msg = f"최신 웹 검색 데이터({', '.join(sites)})"
                                    else:
                                        web_msg = "최신 웹 검색 데이터"
                                        
                                    ref_combine = f"{web_msg}, 그리고 {ref_msg}" if ref_msg else web_msg
                                    active_model_name = st.session_state.get("draft_model", GEMINI_MODEL)
                                    v += f" <br><span style='color:#0284c7; font-size:0.95em; display:inline-block; margin-top:4px;'>➔ <b>[기안서 완결성 보완 (AI 자동 생성 - {active_model_name})]</b> 제공된 초기 자료에 명확한 내용이 없어, 기안서의 문서적 완성도를 높이기 위해 범용적 비즈니스 표준 및 {ref_combine}을(를) 참고하여 AI가 맥락에 맞게 자동으로 작성한 내용입니다.</span>"
                                else:
                                    active_model_name = st.session_state.get("draft_model", GEMINI_MODEL)
                                    if ref_msg:
                                        v += f" <br><span style='color:#0284c7; font-size:0.95em; display:inline-block; margin-top:4px;'>➔ <b>[기안서 완결성 보완 (AI 자동 생성 - {active_model_name})]</b> 제공된 초기 자료에 명확한 내용이 없어, 문서의 완성도를 위해 범용적 비즈니스 표준 및 {ref_msg} 서식을 참고하여 AI가 맥락에 맞게 자동으로 작성한 내용입니다.</span>"
                                    else:
                                        v += f" <br><span style='color:#0284c7; font-size:0.95em; display:inline-block; margin-top:4px;'>➔ <b>[기안서 완결성 보완 (AI 자동 생성 - {active_model_name})]</b> 제공된 초기 자료에 명확한 내용이 없어, 문서의 완성도를 위해 범용적 비즈니스 표준을 참고하여 AI가 맥락에 맞게 자동으로 작성한 내용입니다.</span>"
                            
                            source_html = f"<li style='margin-bottom: 8px;'><strong style='color:#0f172a;'>{k}</strong>: {v}</li>"
                            matched_sources.append(source_html)
                            
                if matched_sources:
                    unique_sources = "".join(set(matched_sources))
                    custom_expander = f"""
                    <details style="border: 1px solid #e2e8f0; border-radius: 8px; margin: 15px auto; background-color: #f8fafc; overflow: hidden; font-family: sans-serif; max-width: 970px;">
                        <summary style="cursor: pointer; padding: 12px 16px; font-weight: 600; color: #334155; list-style: none; display: flex; align-items: center; background-color: #f1f5f9; transition: background-color 0.2s;">
                            <span style="margin-right: 8px; font-size: 1.1em;">💡</span> <span style="font-size: 0.95em;">이 단락의 작성 맥락 및 도출 근거 보기</span>
                        </summary>
                        <div style="padding: 16px; border-top: 1px solid #e2e8f0; color: #475569; font-size: 0.9em; line-height: 1.6; background-color: #ffffff;">
                            <ul style="margin: 0; padding-left: 20px;">
                                {unique_sources}
                            </ul>
                        </div>
                    </details>
                    <style>
                    details > summary::-webkit-details-marker {{ display: none; }}
                    details > summary:hover {{ background-color: #e2e8f0 !important; }}
                    </style>
                    """
                    st.markdown(custom_expander, unsafe_allow_html=True)
                        
                col1, col2, col3 = st.columns([0.7, 0.15, 0.15])
                with col3:
                    with st.popover("💬 Comment", use_container_width=True):
                        st.text_area("단락 수정 지시", key=f"edit_sec_{i}", height=100, placeholder="단락 수정 요청사항 입력...")
                        
    # 신규 단락 추가 UI
    st.markdown("---")
    st.markdown("### ➕ 새로운 단락 추가")
    st.info("💡 기안서 마지막에 누락된 내용(예: 리스크 대응 방안, 향후 일정 등)을 새롭게 작성하여 덧붙일 수 있습니다.")
    
    with st.container(border=True):
        col_t, col_i, col_b = st.columns([0.25, 0.55, 0.2])
        with col_t:
            st.text_input("새 단락 제목", key="new_sec_title", placeholder="예: 리스크 대응 방안")
        with col_i:
            st.text_input("새 단락 내용/지시사항 (선택)", key="new_sec_instr", placeholder="비워두면 AI가 문맥에 맞게 자동 작성")
        with col_b:
            st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
            add_btn = st.button("새 단락 추가 생성", type="primary", use_container_width=True)
            
    if add_btn:
        title = st.session_state.get("new_sec_title", "").strip()
        instr = st.session_state.get("new_sec_instr", "").strip()
        
        if not title:
            st.warning("단락 제목을 입력해주세요.")
        else:
            if not instr:
                instr = f"전체 기안서 문맥을 분석하여 '{title}' 단락에 들어갈 자연스럽고 적절한 내용을 알아서 작성해 줄 것."
                
            with st.spinner("AI가 새로운 단락을 생성하여 추가하고 있습니다..."):
                extracted_facts = st.session_state.get("extracted_facts")
                attachments = st.session_state.get("uploaded_gemini_files")
                full_draft = st.session_state.draft_result
                
                target_model = st.session_state.get("draft_model", GEMINI_MODEL)
                new_sec_html = processor.generate_new_section(
                    title, instr, full_draft, 
                    extracted_facts=extracted_facts, 
                    attachments=attachments, 
                    file_bytes_list=st.session_state.get("uploaded_file_bytes"),
                    target_model=target_model
                )
                new_draft = full_draft + "\n\n" + new_sec_html
                
                if "draft_result_id" in st.session_state:
                    try:
                        db_b.insert_chat_log(
                            result_id=st.session_state.draft_result_id,
                            user_message=f"[신규 단락 추가] {title}: {instr}",
                            before_draft=full_draft,
                            after_draft=new_draft
                        )
                    except Exception as e:
                        print(f"[ERROR] 채팅 이력 DB 저장 오류: {e}")
                        
                st.session_state.draft_result = new_draft
                st.session_state.new_sec_title = ""
                st.session_state.new_sec_instr = ""
                st.rerun()
                
    col1, col2 = st.columns(2)
    with col1:
        if st.button("이전단계", use_container_width=True):
            st.session_state.step = 3
            if "draft_result" in st.session_state:
                del st.session_state["draft_result"]
            st.rerun()
    with col2:
        if st.button("처음화면", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.session_state.step = 1
            st.rerun()
