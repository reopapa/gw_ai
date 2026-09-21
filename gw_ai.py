import time
from datetime import datetime, timedelta
from config import DB_CONFIG_A, DB_CONFIG_B, GEMINI_API_KEY, GEMINI_MODEL, OPENAI_API_KEY, OPENAI_MODEL, QUERY_A, TABLE_AI
from config import START_DATE, END_DATE, BATCH_SIZE
from database import DatabaseManager
from processor import Processor
import argparse


def process_batch(batch_rows, columns, db_b, ai_processor, table_name, target_model):
    """배치(5개 단위) 처리 함수 - 개별 문서 실패 시 ERROR 저장 후 다음 문서 계속 진행"""
    for row in batch_rows:
        data = dict(zip(columns, row))
        print(f"   처리 중: [ID {data['ID']}] {data['Title']}")

        try:
            # 마크다운 변환 및 AI 분석
            content_md = ai_processor.html_to_markdown(data['Content'])
            keywords, summary = ai_processor.analyze_content(content_md, target_model=target_model)

            # 서버 B 저장
            ai_columns = [c for c in columns if c != 'Content']
            ai_data_values = [data[c] for c in ai_columns]
            ai_data_values.extend([keywords, summary])

            placeholders = ", ".join(["?"] * len(ai_data_values))
            cols_str = ", ".join(ai_columns + ["Keywords", "Summary"])

            # 기존 데이터 삭제 후 삽입 (중복 방지)
            db_b.execute(f"DELETE FROM {table_name} WHERE ID = ?", (data['ID'],))
            db_b.execute(f"INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders})", ai_data_values)

            print(f"      => 저장 완료")

        except Exception as doc_err:
            print(f"      [ERROR] ID {data['ID']} 처리 중 오류 발생: {doc_err}")
            print(f"      => 해당 문서를 ERROR 상태로 저장하고 다음 문서로 계속 진행합니다.")
            try:
                # 오류 발생 시 Keywords='ERROR'로 저장하여 나중에 재처리 가능하게 함
                ai_columns = [c for c in columns if c != 'Content']
                error_values = [data[c] for c in ai_columns]
                error_values.extend(["ERROR", str(doc_err)[:500]])
                placeholders = ", ".join(["?"] * len(error_values))
                cols_str = ", ".join(ai_columns + ["Keywords", "Summary"])
                db_b.execute(f"DELETE FROM {table_name} WHERE ID = ?", (data['ID'],))
                db_b.execute(f"INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders})", error_values)
            except Exception as save_err:
                print(f"      [ERROR] ERROR 상태 저장도 실패: {save_err}")


def date_range(start_str, end_str):
    """start_str 부터 end_str 까지 하루씩 날짜를 생성하는 제너레이터"""
    current = datetime.strptime(start_str, "%Y-%m-%d")
    end     = datetime.strptime(end_str,   "%Y-%m-%d")
    while current <= end:
        yield current
        current += timedelta(days=1)


def main():
    parser = argparse.ArgumentParser(description="AI Document Batch Processor")
    parser.add_argument("--provider", type=str, default="gemini", help="Provider to use for data loading (openai or gemini)")
    args = parser.parse_args()
    
    target_model = OPENAI_MODEL if args.provider.lower() == "openai" else GEMINI_MODEL

    total_start = time.time()

    # 1. 초기화
    db_a = DatabaseManager(DB_CONFIG_A)
    db_b = DatabaseManager(DB_CONFIG_B)
    ai_processor = Processor(GEMINI_API_KEY, GEMINI_MODEL, openai_api_key=OPENAI_API_KEY)

    total_processed = 0
    total_skipped = 0

    try:
        # 2. 서버 B 연결 및 테이블 준비
        print("--- 1단계: 서버 B 연결 및 테이블 확인 중... ---")
        db_b.connect()
        db_b.ensure_table_exists(TABLE_AI)
        processed_ids = set(db_b.get_processed_ids(TABLE_AI))
        print(f"이미 처리된 ID 수: {len(processed_ids)}건")

        # 3. 서버 A 연결
        print("\n--- 2단계: 서버 A 연결 중... ---")
        db_a.connect()

        # 4. 날짜 범위 순회
        print(f"\n--- 3단계: [{START_DATE} ~ {END_DATE}] 날짜별 처리 시작 (배치 크기: {BATCH_SIZE}) ---\n")

        for current_date in date_range(START_DATE, END_DATE):
            date_str      = current_date.strftime("%Y-%m-%d")
            next_date_str = (current_date + timedelta(days=1)).strftime("%Y-%m-%d")

            # 해당 날짜 데이터 조회
            columns, rows = db_a.fetch_all_with_params(QUERY_A, (date_str, next_date_str))

            if not rows:
                print(f"[{date_str}] 데이터 없음 - 건너뜀")
                continue

            # 미처리 데이터 필터링
            filtered_rows = [row for row in rows if row[0] not in processed_ids]
            skip_count    = len(rows) - len(filtered_rows)
            total_skipped += skip_count

            print(f"[{date_str}] 전체: {len(rows)}건 / 신규: {len(filtered_rows)}건 / 이미처리: {skip_count}건")

            if not filtered_rows:
                print(f"[{date_str}] 새로 처리할 데이터가 없습니다.\n")
                continue

            # 5개씩 배치 처리
            batch_num = 1
            for i in range(0, len(filtered_rows), BATCH_SIZE):
                batch = filtered_rows[i : i + BATCH_SIZE]
                print(f"  [배치 {batch_num}] {len(batch)}건 처리 중... ({i+1}~{i+len(batch)}/{len(filtered_rows)})")

                process_batch(batch, columns, db_b, ai_processor, TABLE_AI, target_model)

                # 처리된 ID를 즉시 processed_ids 에 추가 (같은 ID가 다른 날짜에 중복 등장 방지)
                for row in batch:
                    processed_ids.add(row[0])

                batch_num += 1
                print()  # 배치 간 빈 줄

            total_processed += len(filtered_rows)
            print(f"[{date_str}] 완료!\n")

    except Exception as e:
        print(f"[FATAL ERROR] {e}")
    finally:
        db_a.close()
        db_b.close()
        elapsed = time.time() - total_start
        print("=" * 60)
        print(f"총 신규 처리: {total_processed}건 / 중복 스킵: {total_skipped}건")
        print(f"소요 시간: {elapsed:.2f}초")
        print("=" * 60)


if __name__ == "__main__":
    main()