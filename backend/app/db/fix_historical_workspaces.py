import os
import sqlite3

workspace_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
db_paths = {
    "Operational DB": os.path.join(workspace_root, "data", "automation_hub_dev.db"),
    "Developer DB": os.path.join(workspace_root, "data", "developer", "automation_hub_dev.db")
}

def fix_db(db_path, name):
    print(f"=== Correcting {name} ({db_path}) ===")
    if not os.path.exists(db_path):
        print("Database file does not exist. Skipping.")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check how many would be updated
        cursor.execute("""
            SELECT COUNT(*) FROM workspace_files 
            WHERE workspace_id IS NULL AND automation_id IS NOT NULL
        """)
        before_count = cursor.fetchone()[0]
        print(f"Files with NULL workspace_id: {before_count}")
        
        if before_count > 0:
            cursor.execute("""
                UPDATE workspace_files 
                SET workspace_id = (
                    SELECT workspace_id 
                    FROM automations 
                    WHERE automations.id = workspace_files.automation_id
                ) 
                WHERE workspace_id IS NULL AND automation_id IS NOT NULL
            """)
            conn.commit()
            print(f"Updated {cursor.rowcount} records successfully.")
            
            # Check remaining
            cursor.execute("""
                SELECT COUNT(*) FROM workspace_files 
                WHERE workspace_id IS NULL AND automation_id IS NOT NULL
            """)
            after_count = cursor.fetchone()[0]
            print(f"Remaining files with NULL workspace_id: {after_count}")
        else:
            print("No records need correction.")
            
    except Exception as e:
        print(f"Error updating database: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    for name, path in db_paths.items():
        fix_db(path, name)
