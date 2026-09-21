from database import DatabaseManager
from config import DB_CONFIG_A, DB_CONFIG_B, TABLE_AI

def main():
    db_a = DatabaseManager(DB_CONFIG_A)
    db_b = DatabaseManager(DB_CONFIG_B)

    db_a.connect()
    db_b.connect()

    query_a = """
    SELECT A.ID, B.Name, B.EACode 
    FROM EAPPDocument A
    INNER JOIN EAPPForm B ON A.FormID = B.ID
    """
    print("Fetching Form data from Server A...")
    cols, rows = db_a.fetch_all(query_a)

    print(f"Updating {len(rows)} rows in Server B ({TABLE_AI})...")
    update_count = 0
    for row in rows:
        doc_id, form_name, ea_code = row
        # 업데이트 쿼리 실행
        try:
            db_b.execute(f"UPDATE {TABLE_AI} SET FormName=?, EACode=? WHERE ID=?", (form_name, ea_code, doc_id))
            update_count += 1
        except Exception as e:
            pass
            
    db_a.close()
    db_b.close()
    print(f"Update completed. {update_count} rows processed.")

if __name__ == "__main__":
    main()
