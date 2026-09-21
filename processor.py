import json
import re
import os
import time
import requests
from google import genai
from markdownify import markdownify as md
from bs4 import BeautifulSoup
import openai

class Processor:
    def __init__(self, api_key, model_name, cohere_api_key=None, openai_api_key=None):
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self.cohere_api_key = cohere_api_key
        self.openai_client = None
        if openai_api_key:
            self.openai_client = openai.OpenAI(api_key=openai_api_key)

    # ===================================================================
    # 헬퍼: 모델 라우팅
    # ===================================================================
    def _is_gpt(self, model_name):
        return str(model_name).lower().startswith("gpt")

    def _require_openai(self):
        if not self.openai_client:
            raise Exception("OpenAI API Key가 설정되지 않았습니다. .env 파일에 OPENAI_API_KEY를 입력해주세요.")

    def _call_gpt(self, model, prompt, json_mode=False):
        self._require_openai()
        kwargs = {"model": model, "messages": [{"role": "user", "content": prompt}]}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = self.openai_client.chat.completions.create(**kwargs)
        return response.choices[0].message.content

    def _call_gpt_with_files(self, model, prompt, file_bytes_list, json_mode=False):
        """GPT Vision API로 파일(이미지/PDF)을 base64로 인코딩하여 전달 - Gemini와 동일한 시각 분석 조건 구현"""
        import base64
        self._require_openai()

        content_parts = [{"type": "text", "text": prompt}]

        for file_info in (file_bytes_list or []):
            raw_bytes = file_info.get("bytes", b"")
            ext = file_info.get("ext", "").lower()
            name = file_info.get("name", "파일")

            # 이미지 파일: 직접 base64 인코딩
            if ext in [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"]:
                mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                            ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}
                mime = mime_map.get(ext, "image/jpeg")
                b64 = base64.standard_b64encode(raw_bytes).decode("utf-8")
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"}
                })

            # PDF 파일: 각 페이지를 이미지로 변환 후 전달
            elif ext == ".pdf":
                try:
                    import pymupdf
                    doc = pymupdf.open(stream=raw_bytes, filetype="pdf")
                    for page_num in range(min(len(doc), 10)):  # 최대 10페이지
                        page = doc.load_page(page_num)
                        mat = pymupdf.Matrix(2.0, 2.0)  # 2x 해상도
                        pix = page.get_pixmap(matrix=mat)
                        img_bytes = pix.tobytes("png")
                        b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
                        content_parts.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"}
                        })
                    doc.close()
                except ImportError:
                    print(f"[INFO] PyMuPDF(pymupdf) 미설치 - PDF '{name}'은 텍스트(extracted_facts)로만 처리됩니다.")
                except Exception as e:
                    print(f"[WARN] PDF to image 변환 실패 ({name}): {e}")

            # Excel/기타 파일: 텍스트 컨텍스트(extracted_facts)로 이미 처리됨 - 스킵
            else:
                print(f"[INFO] '{name}' ({ext}) 파일은 비전 전달 불가 - extracted_facts 텍스트로 대체됩니다.")

        kwargs = {"model": model, "messages": [{"role": "user", "content": content_parts}]}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = self.openai_client.chat.completions.create(**kwargs)
        return response.choices[0].message.content


    def _call_gemini(self, model, contents, json_mode=False, use_search=False):
        config = {}
        if json_mode:
            config["response_mime_type"] = "application/json"
        if use_search:
            config["tools"] = [{"google_search": {}}]
        response = self.client.models.generate_content(
            model=model,
            contents=contents,
            config=config if config else None
        )
        return response

    # ===================================================================
    # 의도 파악
    # ===================================================================
    def check_request_intent(self, user_request):
        prompt = f"""
        당신은 사내 그룹웨어 전자결재 시스템의 AI 어시스턴트입니다.
        사용자의 입력 문장을 분석하여, 이것이 기안서나 품의서 같은 '전자결재 문서 작성(또는 초안 작성)'을 요구하는 명령어인지 파악해주세요.
        
        사용자 입력:
        "{user_request}"
        
        지시사항:
        1. 만약 문서 작성(또는 관련 데이터 검색 후 작성) 요구라면 "is_draft_request": true 로 설정하세요.
        2. 만약 문서 작성이 아닌 단순 질문, 인사, 일상 대화, 시스템 사용법 문의 등이라면 "is_draft_request": false 로 설정하고, "response_message"에 사용자에게 친절하게 제공할 답변을 작성하세요.
        3. 반환값은 반드시 아래의 JSON 포맷만 출력하세요.
        
        {{
            "is_draft_request": boolean,
            "response_message": "단순 대화나 질문에 대한 답변 (기안 요청일 경우 빈 문자열)"
        }}
        """
        try:
            response = self._call_gemini(self.model_name, prompt, json_mode=True)
            result = json.loads(response.text)
            return result.get("is_draft_request", True), result.get("response_message", "")
        except Exception as e:
            print(f"[ERROR] 의도 파악 API 호출 중 오류: {e}")
            return True, ""

    # ===================================================================
    # 파일 업로드 / 대기
    # ===================================================================
    def wait_for_file_active(self, file_obj, timeout=60):
        if not file_obj:
            return None
        start_time = time.time()
        curr_file = file_obj
        try:
            while hasattr(curr_file, 'state') and hasattr(curr_file.state, 'name') and curr_file.state.name == 'PROCESSING':
                if time.time() - start_time > timeout:
                    print(f"[WARNING] 파일 처리 시간 초과: {getattr(curr_file, 'name', '')}")
                    break
                print(f"Waiting for file {getattr(curr_file, 'name', '')} to process...")
                time.sleep(2)
                curr_file = self.client.files.get(name=curr_file.name)
        except Exception as e:
            print(f"[WARNING] 파일 상태 확인 중 예외: {e}")
        return curr_file

    def upload_file(self, file_path, wait_active=True):
        upload_path = file_path
        temp_csv = None
        
        try:
            ext = os.path.splitext(file_path)[1].lower()
            if ext in ['.xlsx', '.xls']:
                try:
                    import pandas as pd
                    print(f"[{file_path}] 엑셀 파일을 텍스트(TSV) 형식으로 변환 중...")
                    
                    xls = pd.read_excel(file_path, sheet_name=None, header=None)
                    
                    content = ""
                    for sheet_name, df in xls.items():
                        df = df.dropna(how='all', axis=1).dropna(how='all', axis=0).fillna("")
                        if df.empty:
                            continue
                            
                        content += f"=== Sheet: {sheet_name} ===\n"
                        
                        df_str = df.astype(str).replace(r'\n', ' ', regex=True).replace(r'\|', '-', regex=True)
                        num_cols = len(df_str.columns)
                        header = "| " + " | ".join([f"Col{i}" for i in range(num_cols)]) + " |"
                        separator = "| " + " | ".join(["---"] * num_cols) + " |"
                        
                        content += header + "\n" + separator + "\n"
                        for _, row in df_str.iterrows():
                            content += "| " + " | ".join(row.tolist()) + " |\n"
                        content += "\n\n"
                        
                    temp_csv = file_path + ".txt"
                    with open(temp_csv, "w", encoding="utf-8") as f:
                        f.write(content)
                        
                    upload_path = temp_csv
                except Exception as e:
                    print(f"[ERROR] 엑셀 변환 실패: {e}")
                    raise Exception(f"엑셀 변환 실패: {e}")
            print(f"[{upload_path}] 파일 구글 서버로 업로드 중...")
            uploaded_file = self.client.files.upload(file=upload_path)
            print(f"[{file_path}] 파일 업로드 완료 (URI: {uploaded_file.uri})")
            
            if temp_csv and os.path.exists(temp_csv):
                try:
                    os.remove(temp_csv)
                except Exception:
                    pass
                
            if wait_active:
                uploaded_file = self.wait_for_file_active(uploaded_file)
                
            return uploaded_file
        except Exception as e:
            print(f"[ERROR] 파일 업로드 중 오류 발생 ({file_path}): {e}")
            if temp_csv and os.path.exists(temp_csv):
                try:
                    os.remove(temp_csv)
                except Exception:
                    pass
            raise Exception(f"Gemini 서버 업로드 오류: {e}")

    # ===================================================================
    # 양식 필수 항목 추출
    # ===================================================================
    def generate_form_questions(self, form_name, doc_summary="", attachments=None):
        prompt = f"""
        당신은 사내 전자결재 문서 작성 도우미입니다.
        사용자가 '{form_name}' 양식의 기안/품의서를 작성하려고 합니다.
        문서의 대략적인 내용은 다음과 같습니다: "{doc_summary if doc_summary else '미지정'}"
        
        해당 양식과 내용(첨부파일 포함)을 바탕으로, 이 문서를 작성할 때 필수적으로 들어가야 할 핵심 항목(예: 목적, 예산, 일정 등) 2~5가지를 맞춤형으로 추출해주세요.
        
        결과는 반드시 아래 JSON 형식으로만 응답해주세요:
        {{
          "essential_fields": ["항목1", "항목2", "항목3"]
        }}
        """
        
        contents = []
        if attachments:
            for file_obj in attachments:
                if file_obj:
                    active_f = self.wait_for_file_active(file_obj) if hasattr(file_obj, 'name') else file_obj
                    if active_f:
                        contents.append(active_f)
        contents.append(prompt)
        
        try:
            response = self._call_gemini(self.model_name, contents, json_mode=True)
            result = json.loads(response.text)
            return result.get("essential_fields", ["작성 목적", "상세 내용", "기대 효과"])
        except Exception as e:
            print(f"[ERROR] 필수 항목 추출 중 오류: {e}")
            return ["작성 목적", "상세 내용", "기대 효과"]

    # ===================================================================
    # 첨부파일 팩트 추출 (항상 Gemini 비전 사용 - GPT에도 전달됨)
    # ===================================================================
    def extract_attachment_facts(self, attachments):
        if not attachments:
            return ""
        prompt = """
        사용자가 업로드한 첨부파일(견적서, 쇼핑몰 장바구니 스크린샷, 영수증, 구매 내역 이미지, 기안서, 제안서 등)을 정밀 분석하여, 다음 정보를 빠짐없이 정확하게 추출하세요.
        1. 거래처/판매처 상호명 (쇼핑몰 스크린샷의 경우 쇼핑몰 이름(예: 쿠팡) 또는 '온라인 구매'로 기재)
        2. 품목 리스트 (각 품목의 정확한 품명, 옵션/규격, 수량, 단가, 총금액 등)
        3. 문서 전체 텍스트 (도입 배경, 목적, 계약 조건, 유의사항 등 표 데이터를 제외한 모든 텍스트 원문)
        
        결과는 반드시 아래 JSON 형식으로만 응답해주세요. 이미지 및 문서에 있는 실제 숫자와 품목명, 그리고 텍스트 원문을 절대적으로 신뢰하고 빠짐없이 추출하세요.
        {
          "supplier": "거래처 또는 판매처 상호명",
          "items": [
            {
              "name": "품명 및 모델명",
              "spec": "규격 및 옵션",
              "unit": "단위(EA, 개, 대 등)",
              "quantity": "수량",
              "price": "단가",
              "total_amount": "금액"
            }
          ],
          "document_full_text": "첨부파일 내에 기재된 도입 배경, 목적, 계약 조건, 보증 기간, 세부 설명 등 모든 텍스트 원문을 마크다운 형식으로 상세히 복원한 내용"
        }
        """
        contents = [prompt]
        for f in attachments:
            if f:
                active_f = self.wait_for_file_active(f) if hasattr(f, 'name') else f
                if active_f:
                    contents.append(active_f)
        try:
            # 항상 Gemini 비전으로 파일을 분석 (GPT는 파일을 직접 읽지 못하므로 결과 텍스트를 전달)
            response = self._call_gemini(self.model_name, contents, json_mode=True)
            return response.text
        except Exception as e:
            print(f"[ERROR] 첨부파일 데이터 사전 추출 실패: {e}")
            return ""

    # ===================================================================
    # HTML → 마크다운 변환
    # ===================================================================
    def html_to_markdown(self, html_content):
        if not html_content:
            return ""
        soup = BeautifulSoup(html_content, 'html.parser')
        return md(str(soup), heading_style="ATX")

    # ===================================================================
    # 문서 분석 (키워드 + 요약)
    # ===================================================================
    def analyze_content(self, content_md, target_model=None):
        if not content_md or len(content_md.strip()) == 0:
            return "N/A", "내용 없음"
        
        active_model = target_model or self.model_name
        
        prompt = f"""
        다음은 문서의 내용입니다. 마크다운 형식으로 되어 있습니다.
        이 내용에서 다음 두 가지를 추출해주세요:
        1. 주요 키워드 10개 (쉼표로 구분)
        2. 전체 내용에 대한 요약본 (3-5문장)

        결과는 반드시 아래 JSON 형식으로만 응답해주세요:
        {{
          "keywords": "키워드1, 키워드2, ...",
          "summary": "요약 내용..."
        }}

        문서 내용:
        {content_md}
        """
        try:
            if self._is_gpt(active_model):
                result = json.loads(self._call_gpt(active_model, prompt, json_mode=True))
            else:
                response = self._call_gemini(active_model, prompt, json_mode=True)
                result = json.loads(response.text)
            return result.get('keywords', 'N/A'), result.get('summary', '요약 실패')
        except Exception as e:
            print(f"[ERROR] 문서 분석 API 호출 중 오류: {e}")
            return "ERROR", str(e)

    # ===================================================================
    # 유사 문서 검색 (Gemini 고정 - 메타데이터만 처리)
    # ===================================================================
    def find_top_25_similar(self, user_request, documents, form_name=""):
        if not documents:
            return []
            
        docs_text = ""
        for d in documents:
            doc_form_name = d.get('FormName', '미지정')
            ea_code = d.get('EACode', '미지정')
            docs_text += f"[ID: {d['ID']}] 제목: {d['Title']} | 양식: {doc_form_name}({ea_code})\n키워드: {d['Keywords']}\n요약: {d['Summary']}\n\n"
            
        prompt = f"""
        사용자가 사내 전자결재 문서를 작성하려고 합니다. 
        다음은 기존 전자결재 문서들(ID, 제목, 사용된 결재 양식, 키워드, 요약) 정보입니다.
        
        작성 예정 양식: {form_name if form_name else '미지정'}
        사용자 요청 내용 (및 기입 항목):
        "{user_request}"
        
        지시사항:
        1. 작성 예정 양식과 사용자 요청 내용을 분석하여, 목적에 부합하는 문서(특히 '양식(FormName/EACode)' 정보가 일치하거나 유사한) 상위 25개의 ID를 선정해주세요.
        2. 'search_query' 필드에는 리랭커 모델이 유사한 문서를 잘 찾을 수 있도록 검색어(예: "출장 회의록", "휴가 신청")를 추출해서 작성해주세요.
        3. 응답은 반드시 아래의 JSON 형식으로만 제공해주세요.
        
        {{
          "search_query": "검색용 핵심 키워드",
          "top25_ids": [id1, id2, ..., id25]
        }}
        
        문서 목록:
        {docs_text}
        """
        try:
            response = self._call_gemini(self.model_name, prompt, json_mode=True)
            result = json.loads(response.text)
            return result.get('search_query', user_request), result.get('top25_ids', [])
        except Exception as e:
            print(f"[ERROR] 1차 유사도 분석 API 호출 중 오류: {e}")
            return user_request, []

    # ===================================================================
    # Cohere 리랭킹
    # ===================================================================
    def rerank_to_top_3(self, search_query, top25_documents, threshold=0.005):
        if not top25_documents:
            return []
            
        if not self.cohere_api_key or self.cohere_api_key == "여기에_Cohere_API_키_입력":
            print("[ERROR] Cohere API 키가 설정되지 않았습니다. config.py 파일에 COHERE_API_KEY를 입력해주세요.")
            return []
            
        doc_texts = []
        for d in top25_documents:
            form_name = d.get('FormName', '미지정')
            ea_code = d.get('EACode', '미지정')
            doc_text = f"[ID: {d['ID']}] 제목: {d['Title']} | 양식: {form_name}({ea_code})\n키워드: {d['Keywords']}\n요약: {d['Summary']}"
            doc_texts.append(doc_text)
            
        try:
            url = "https://api.cohere.com/v1/rerank"
            headers = {
                "Authorization": f"Bearer {self.cohere_api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "rerank-multilingual-v3.0",
                "query": search_query,
                "documents": doc_texts,
                "top_n": 3
            }
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            
            result = response.json()
            top3_results = []
            for item in result.get('results', []):
                score = item.get('relevance_score', 0.0)
                if score < threshold:
                    print(f"점수 미달로 제외됨: ID {top25_documents[item['index']]['ID']}, Score: {score:.4f}")
                    continue
                idx = item['index']
                top3_results.append({
                    'ID': top25_documents[idx]['ID'],
                    'Title': top25_documents[idx].get('Title', 'No Title'),
                    'Score': score
                })
                
            return top3_results
        except Exception as e:
            print(f"[ERROR] Cohere 리랭커 API 호출 중 오류: {e}")
            return []

    # ===================================================================
    # 필수 체크리스트 생성
    # ===================================================================
    def generate_essential_checklist(self, user_request, top3_contents, extracted_facts=None, attachments=None, file_bytes_list=None, target_model=None):
        active_model = target_model or self.model_name
        if not top3_contents:
            contents_text = "서버 내 관련된 참고 문서가 없습니다."
        else:
            contents_text = ""
            for i, content in enumerate(top3_contents):
                contents_text += f"--- 참고 문서 {i+1} ---\n{content}\n\n"
                
        prompt = f"""
        당신은 최고의 기안서 작성 전문가입니다.
        사용자가 기안서를 작성하려고 합니다. 당신의 임무는 "완벽한 기안서를 위해 반드시 필요한 **표준 핵심 요소(Standard Checklist) 5~7가지**"를 먼저 객관적으로 정의하고, 사용자가 제공한 자료에 그 내용이 있는지 팩트 체크하는 것입니다.
        
        [사용자 요약 및 요구사항]
        {user_request}
        
        [과거 유사 문서(참고용)]
        {contents_text}
        """
        
        if extracted_facts:
            prompt += f"""
        [추출된 팩트 데이터(견적 등)]
        {extracted_facts}
        """
        
        prompt += """
        
        출력 형식 (반드시 JSON 배열 형태로 반환):
        [
            {
                "item": "핵심 요소명 (예: 도입 배경 및 목적, 총 소요 예산, 기대 효과(ROI), 유지보수 방안, 예산 확보 방안 등)",
                "value": "제공된 자료(요약, 팩트 데이터, 첨부파일)에서 해당 항목에 대한 구체적인 내용을 찾은 경우 그 값을 요약해서 작성. 만약 정보가 전혀 없거나 부족하다면 빈 문자열 \"\" 반환",
                "source": "이 값을 채웠거나 비워둔 이유 (예: '첨부된 견적서 2페이지 합계 금액 반영', '기술적 사양만 존재하여 비즈니스 기대 효과는 누락됨' 등)"
            }
        ]
        
        규칙:
        1. JSON 배열 외에 다른 텍스트는 출력하지 마세요.
        2. [매우 중요] 현재 제공된 자료(팩트 데이터 등)에 있는 내용에만 맞춰서 항목을 만들지 마세요! 이런 종류의 기안서가 통상적으로 결재를 통과하기 위해 객관적으로 반드시 갖춰야 할 **"이상적인 표준 항목"**을 5~7개(최대 10개) 도출하세요.
        3. 그 후, 표준 항목 중 자료에 있는 것은 값을 채우고(`value`), 자료에 없는 필수 항목(예: ROI, 예산 확보 방안, 보안 대책 등)은 과감하게 빈칸(`value: ""`)으로 두어 사용자에게 입력을 유도해야 합니다.
        4. 단가표, 품목 상세 내역 등 세부적인 표 데이터는 이미 추출되었으므로 체크리스트 항목으로 묻지 마세요. 큰 그림(목적, 예산, 기대효과 등) 위주로 구성하세요.
        """
        
        try:
            if self._is_gpt(active_model):
                if file_bytes_list:
                    return self._call_gpt_with_files(active_model, prompt, file_bytes_list)
                return self._call_gpt(active_model, prompt)
            else:
                contents = [prompt]
                if attachments:
                    for f in attachments:
                        if f:
                            active_f = self.wait_for_file_active(f) if hasattr(f, 'name') else f
                            if active_f:
                                contents.append(active_f)
                response = self._call_gemini(active_model, contents, json_mode=True)
                return response.text
        except Exception as e:
            print(f"[ERROR] 체크리스트 생성 API 호출 중 오류: {e}")
            return "[]"

    # ===================================================================
    # 초안 생성
    # ===================================================================
    def generate_draft(self, user_request, top3_contents, use_web_search=False, extracted_facts=None, attachments=None, file_bytes_list=None, essential_answers=None, excluded_items=None, target_model=None):
        active_model = target_model or self.model_name
        if not top3_contents:
            contents_text = "서버 내 관련된 참고 문서가 없습니다. 일반적인 기안 양식을 활용합니다."
        else:
            contents_text = ""
            for i, content in enumerate(top3_contents):
                contents_text += f"--- 참고 문서 {i+1} ---\n{content}\n\n"
            
        has_facts = bool(extracted_facts)
        
        if has_facts:
            attachment_rules = f"""
        1. 당신은 전문 기안서 편집자입니다. <past_reference_documents>는 과거에 작성된 유사 기안서입니다. (중요) 비록 이번에 작성할 새로운 기안서의 단락 제목(목차)이 과거 문서와 다르더라도, 과거 문서에 있는 유용한 표 구조(서식)와 전체적인 양식을 문맥에 맞게 매핑하여 적극 재사용하세요.
        2. (초격차 중요) 단, 이번 기안의 핵심 수치와 내용은 반드시 아래 제공된 [주입할 팩트 데이터(JSON)]를 100% 반영하여 과거 문서의 내용을 '덮어씌워야' 합니다.
        3. 과거 문서에 여러 개의 표(품목 표, 예산 표, 비교 견적 표 등)가 있다면, [주입할 팩트 데이터(JSON)]의 '총액'과 '거래처명'을 기준으로 모든 표의 내용을 논리적으로 앞뒤가 맞게 스스로 수정하고 계산하세요. (예: 팩트 데이터에 A업체가 있다면, 비교 견적 표의 선정 업체도 A업체로 수정되어야 함)
        4. (매우 중요) 과거 문서에만 있던 불필요한 품목(예: 기존 기안에는 3개 품목이었으나 새 팩트에는 1개만 있는 경우)은 결과물 표에서 반드시 삭제하세요.
        5. (첨부파일 종합 분석) 사용자가 첨부한 원본 파일들(일정표, WBS, 제안서 등)도 함께 제공됩니다. 견적 수치가 아닌 '프로젝트 일정, 단계, 아키텍처 등'의 추가 정보는 첨부파일 내용을 꼼꼼히 분석하여 기안서의 적절한 위치(예: 구축 프로젝트 일정 표 등)에 완벽하게 반영하세요.
        
        [주입할 팩트 데이터(JSON)]
        {extracted_facts}
        """
        else:
            attachment_rules = """
        1. 정보의 역할 분담: 사용자가 별도의 첨부파일 팩트를 제공하지 않았으므로, 과거 참고 문서의 서식(표 형태)과 샘플 데이터를 바탕으로 초안을 풍성하게 작성하세요. (중요) 비록 새 기안서의 단락 제목이 과거 문서와 다르더라도, 과거 문서의 유용한 표 양식을 새 단락의 문맥에 맞게 유연하게 끌어와서 재사용해야 합니다.
        2. 과거 문서에 있는 품목이나 내역 등을 가상의 샘플 예시로 활용해도 좋으나, 사용자가 직접 기입한 요구사항이 있다면 기입 내용을 우선하여 수정하세요.
        3. 내용이 부족할 경우 문맥을 통해 논리적으로 표와 본문을 채워 넣으세요.
        4. (첨부파일 활용) 만약 사용자가 첨부한 원본 파일(일정표 등)이 제공된다면, 해당 내용을 정밀하게 시각적으로 분석하여 기안서 내용으로 적극 반영하세요."""

        prompt = f"""
        사용자가 새로운 기안을 작성하려고 합니다.
        
        사용자가 기입한 내용 (사용자 직접 입력항목 영역):
        {user_request}
        
        <past_reference_documents>
        {contents_text}
        </past_reference_documents>
        """
        
        if essential_answers:
            answers_text = ""
            for k, v in essential_answers.items():
                if v and str(v).strip():
                    answers_text += f"- {k}: {v}\n"
                else:
                    answers_text += f"- {k}: (사용자가 비워둠. 문맥과 제공된 자료를 바탕으로 최적의 내용을 AI가 스스로 판단하여 채워주세요)\n"
            
            prompt += f"""
        [필수 체크리스트 사용자 답변]
        {answers_text}
        """
        
        if excluded_items:
            excluded_text = ", ".join(excluded_items)
            prompt += f"""
        [명시적 제외 항목 (초격차 중요)]
        사용자가 다음 항목들은 문서에서 완전히 제외하도록 명시적으로 선택했습니다: [{excluded_text}]
        과거 참고 문서에 해당 내용이 있더라도, 이번 결과물 기안서에는 해당 항목(단락, 제목, 표 등)을 절대로 생성하지 마세요!
        """
        
        prompt += f"""
        작성 지침 (절대 규칙):{attachment_rules}
        4. (매우 중요) 기안서 상단의 결재선 및 기본 정보 테이블(문서번호, 보존년한, 작성부서, 작성일자, 작성자, 시행일자 등)은 절대 생성하지 마세요. 
        5. 결과물은 오직 문서의 '제목(제 목)'과 '본문 내용(개요, 목적, 세부사항 등)' 부분만을 포함하여 작성할 것.
        6. 결과물은 순수 HTML 태그 형식으로 작성할 것 (마크다운 백틱(```html) 등은 제외하고 HTML 태그만 반환할 것).
        7. 표(Table) 형태가 필요하다면, 반드시 HTML의 <table>, <tr>, <td>, <th> 태그를 사용하되, 보기 좋게 인라인 CSS(예: style="border-collapse: collapse; width: 100%; text-align: center;", border="1", 배경색 등)를 꼼꼼히 적용하여 '디자인이 잘 꾸며진 표'를 구현할 것.
        8. (초격차 중요) 본문의 각 단락(예: 목적, 개요, 예산, 일정 등)은 반드시 HTML 헤딩 태그(<h2> 또는 <h3>)로 시작하여 명확하게 단락을 구분해야 합니다.
        9. (텍스트 가독성 극대화) 핵심 키워드나 중요한 수치, 결론 등은 반드시 <b>나 <strong> 태그를 사용해 굵게 처리하거나 폰트 색상을 입혀 시각적으로 강조하세요. 항목을 나열할 때는 줄글 대신 <ul>, <ol>, <li> 태그를 적극적으로 활용해 세련되고 잘 정돈된 문서 레이아웃을 만드세요.
        10. (단락 제목 엄수) 결과물 기안서의 각 단락 제목(<h2> 또는 <h3>)은 반드시 위 [필수 체크리스트 사용자 답변]에 나열된 항목 이름(키워드)을 100% 그대로 사용하여 구성하세요. 임의로 단락 제목을 변경하거나 과거 문서의 제목을 섞어 쓰지 마세요.
        """
        
        if use_web_search:
            if has_facts:
                prompt += "\n9. (웹 검색) 문서 요약 내용과 주입된 팩트를 바탕으로, 기안서 작성의 타당성이나 배경 설명(최신 동향, 제품 스펙, 시장 환경 등)에 필요한 '중요 정보'를 웹 검색을 통해 찾아내어 본문(개요나 사유 등)에 자연스럽게 추가하세요. (단, 팩트 데이터로 제공된 견적 수치와 거래처는 웹 검색 결과로 절대 변경 불가). 만약 웹사이트 정보를 참고했다면, 응답 HTML의 맨 마지막에 반드시 `<!-- WEB_SOURCES: [{\"title\":\"사이트명\", \"uri\":\"http...\"}, ...] -->` 형태의 주석으로 참고한 출처를 남겨주세요."
            else:
                prompt += "\n9. (웹 검색) 문서 요약 내용을 바탕으로, 기안서 작성의 타당성이나 배경 설명(최신 동향, 관련 규정, 제품 스펙 등)에 필요한 '중요 정보'를 웹 검색을 통해 찾아내어 본문에 자연스럽게 추가하세요. 만약 웹사이트 정보를 참고했다면, 응답 HTML의 맨 마지막에 반드시 `<!-- WEB_SOURCES: [{\"title\":\"사이트명\", \"uri\":\"http...\"}, ...] -->` 형태의 주석으로 참고한 출처를 남겨주세요."
            
        self.last_web_sources = []

        try:
            if self._is_gpt(active_model):
                if file_bytes_list:
                    text_result = self._call_gpt_with_files(active_model, prompt, file_bytes_list)
                else:
                    text_result = self._call_gpt(active_model, prompt)
                return text_result
            else:
                contents = [prompt]
                if attachments:
                    for f in attachments:
                        if f:
                            active_f = self.wait_for_file_active(f) if hasattr(f, 'name') else f
                            if active_f:
                                contents.append(active_f)

                config_kwargs = {}
                if use_web_search:
                    config_kwargs['tools'] = [{"google_search": {}}]

                response = self._call_gemini(active_model, contents, use_search=use_web_search)

                # 웹 검색 출처 추출
                try:
                    if use_web_search and hasattr(response, 'candidates') and response.candidates:
                        metadata = getattr(response.candidates[0], 'grounding_metadata', None)
                        if metadata and hasattr(metadata, 'grounding_chunks'):
                            for chunk in metadata.grounding_chunks:
                                if hasattr(chunk, 'web') and chunk.web:
                                    self.last_web_sources.append({"title": getattr(chunk.web, 'title', ''), "uri": getattr(chunk.web, 'uri', '')})
                    
                    # SDK 메타데이터 추출 실패 시 프롬프트 기반 fallback
                    if not self.last_web_sources and use_web_search:
                        match = re.search(r'<!--\s*WEB_SOURCES:\s*(\[.*?\])\s*-->', response.text, re.DOTALL)
                        if match:
                            self.last_web_sources = json.loads(match.group(1))
                except Exception as extract_err:
                    print(f"[WARN] Failed to extract web sources: {extract_err}")

                return response.text
        except Exception as e:
            print(f"[ERROR] 초안 작성 API 호출 중 오류: {e}")
            return str(e)

    # ===================================================================
    # HTML → 단락 분리
    # ===================================================================
    def split_html_into_sections(self, html_content):
        soup = BeautifulSoup(html_content, "html.parser")
        
        # 1. 의미 있는 태그 자식만 반환하는 헬퍼 함수
        def get_meaningful_tags(element):
            return [c for c in element.children if c.name is not None]

        # 2. 최상위에 단일 래퍼(div, article, body 등)로 감싸져 있다면 껍질을 벗겨냄
        current_root = soup
        while True:
            tags = get_meaningful_tags(current_root)
            if len(tags) == 1 and tags[0].name not in ['h1', 'h2', 'h3', 'table']:
                current_root = tags[0]
            else:
                break
                
        container = current_root
        
        sections = []
        current_section = ""
        for child in container.children:
            if child.name in ['h1', 'h2', 'h3']:
                if current_section.strip():
                    sections.append(current_section)
                current_section = str(child)
            else:
                current_section += str(child)
                
        if current_section.strip():
            sections.append(current_section)
            
        return sections

    # ===================================================================
    # 단락 수정 (GPT/Gemini 라우팅)
    # ===================================================================
    def refine_draft_section(self, section_html, user_message, full_draft, extracted_facts=None, attachments=None, file_bytes_list=None, target_model=None):
        active_model = target_model or self.model_name
        prompt = f"""
        당신은 기안서 전문 편집자입니다.
        전체 기안서의 문맥을 고려하되, 오직 아래 제공된 [수정 대상 단락(HTML)]의 내용만을 사용자의 [수정 요청사항]에 맞게 부분 수정하여 반환해야 합니다.
        
        [전체 기안서 문맥 참조용 (수정 불필요)]
        {full_draft}
        
        [수정 요청사항]
        {user_message}
        
        [수정 대상 단락(HTML) - 오직 이 부분만 새롭게 작성해서 반환할 것]
        {section_html}
        """
        
        if extracted_facts:
            prompt += f"""
        
        [원본 팩트 데이터(JSON)]
        {extracted_facts}
        """

        prompt += """
        
        작성 지침 (절대 규칙):
        1. 결과물은 반드시 수정된 단락의 순수 HTML 태그 형식으로만 반환할 것 (마크다운 백틱(```html) 등은 제외).
        2. 제공된 [수정 대상 단락]의 HTML 구조(표, 리스트 등)를 가급적 유지하면서 내용만 수정할 것. 단, 표(Table)가 들어가는 경우 인라인 CSS(예: style="border-collapse: collapse;", border="1", 헤더 배경색 등)를 적극 적용해 세련되게 꾸밀 것.
        3. 전체 기안서가 아닌, 오직 해당 단락에 대한 HTML 코드만 출력할 것.
        4. 사용자가 지워진 표를 복구하거나 세부 내용을 다시 적어달라고 요청하는 경우, 제공된 [원본 팩트 데이터] 및 첨부된 원본 파일들의 내용을 바탕으로 누락 없이 작성할 것. 절대로 임의의 데이터를 지어내지 말 것.
        5. (텍스트 꾸미기) 텍스트 내 중요한 키워드나 수치는 <b> 태그 등을 사용해 시각적으로 강조하고, 나열형 데이터는 <ul>, <li>로 깔끔하게 정리해 세련된 문서를 만드세요.
        """
        
        try:
            if self._is_gpt(active_model):
                if file_bytes_list:
                    return self._call_gpt_with_files(active_model, prompt, file_bytes_list)
                return self._call_gpt(active_model, prompt)
            else:
                contents = [prompt]
                if attachments:
                    for f in attachments:
                        if f:
                            active_f = self.wait_for_file_active(f) if hasattr(f, 'name') else f
                            if active_f:
                                contents.append(active_f)
                response = self._call_gemini(active_model, contents)
                return response.text
        except Exception as e:
            print(f"[ERROR] 단락 수정 API 호출 중 오류: {e}")
            return section_html

    # ===================================================================
    # 신규 단락 생성 (GPT/Gemini 라우팅)
    # ===================================================================
    def generate_new_section(self, section_title, instruction, full_draft, extracted_facts=None, attachments=None, file_bytes_list=None, target_model=None):
        active_model = target_model or self.model_name
        prompt = f"""
        당신은 기안서 전문 작성자입니다.
        아래 제공된 [전체 기안서 문맥 참조용]을 읽고, 기안서 흐름에 자연스럽게 이어지도록 **새로운 단락**을 하나 작성해야 합니다.
        
        [전체 기안서 문맥 참조용]
        {full_draft}
        
        [새로운 단락 제목]
        {section_title}
        
        [단락 작성 지시사항]
        {instruction}
        """
        
        if extracted_facts:
            prompt += f"""
        
        [원본 팩트 데이터(JSON)]
        {extracted_facts}
        """

        prompt += """
        
        작성 지침 (절대 규칙):
        1. 결과물은 반드시 순수 HTML 태그 형식으로만 반환할 것 (마크다운 백틱(```html) 등은 제외).
        2. 기안서의 다른 단락들과 시각적, 논리적 일관성을 유지하도록 <h2> 태그로 단락 제목을 시작할 것.
        3. 전체 기안서가 아닌, 오직 새로 작성한 1개의 단락에 대한 HTML 코드만 출력할 것.
        4. 사용자가 요청한 [단락 작성 지시사항]을 충실히 반영할 것.
        """
        
        try:
            if self._is_gpt(active_model):
                if file_bytes_list:
                    return self._call_gpt_with_files(active_model, prompt, file_bytes_list)
                return self._call_gpt(active_model, prompt)
            else:
                contents = [prompt]
                if attachments:
                    for f in attachments:
                        if f:
                            active_f = self.wait_for_file_active(f) if hasattr(f, 'name') else f
                            if active_f:
                                contents.append(active_f)
                response = self._call_gemini(active_model, contents)
                return response.text
        except Exception as e:
            print(f"[ERROR] 신규 단락 생성 API 호출 중 오류: {e}")
            return f"<h2>{section_title}</h2><p>단락 생성 중 오류가 발생했습니다: {e}</p>"

    # ===================================================================
    # 전체 초안 수정 (GPT/Gemini 라우팅)
    # ===================================================================
    def refine_draft(self, current_draft, user_message, extracted_facts=None, attachments=None, file_bytes_list=None, target_model=None):
        active_model = target_model or self.model_name
        prompt = f"""
        당신은 기안서 전문 편집자입니다.
        아래 [현재 기안서 초안(HTML)]을 보고, 사용자의 [수정 요청사항]에 맞게 기안서를 즉석에서 수정하여 다시 작성해주세요.
        
        [수정 요청사항]
        {user_message}
        
        [현재 기안서 초안(HTML)]
        {current_draft}
        """
        
        if extracted_facts:
            prompt += f"""
        
        [원본 팩트 데이터(JSON)]
        {extracted_facts}
        """

        prompt += """
        
        작성 지침 (절대 규칙):
        1. 결과물은 반드시 순수 HTML 태그 형식으로 작성할 것 (마크다운 백틱(```html) 등은 제외하고 반환).
        2. 기안서 양식에 맞게 자연스럽고 프로페셔널한 비즈니스 어조를 유지할 것.
        3. (매우 중요) 사용자가 지워진 표를 복구하거나 세부 내용을 다시 적어달라고 요청하는 경우, 제공된 [원본 팩트 데이터] 및 첨부된 원본 파일들의 내용을 바탕으로 누락 없이 작성할 것. 절대로 임의의 데이터를 지어내지 말 것.
        """
        
        try:
            if self._is_gpt(active_model):
                if file_bytes_list:
                    return self._call_gpt_with_files(active_model, prompt, file_bytes_list)
                return self._call_gpt(active_model, prompt)
            else:
                contents = [prompt]
                if attachments:
                    for f in attachments:
                        if f:
                            active_f = self.wait_for_file_active(f) if hasattr(f, 'name') else f
                            if active_f:
                                contents.append(active_f)
                response = self._call_gemini(active_model, contents)
                return response.text
        except Exception as e:
            print(f"[ERROR] 초안 수정 API 호출 중 오류: {e}")
            return str(e)
