import os
import sqlite3

def reset_db(db_path):
    if not os.path.exists(db_path):
        print(f"Banco de dados nao encontrado: {db_path}")
        return
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Vamos contar quantos usuarios estao conectados
        cursor.execute("SELECT COUNT(*) FROM users WHERE playground_connected = 1;")
        count_before = cursor.fetchone()[0]
        
        cursor.execute("UPDATE users SET playground_connected = 0, playground_session_path = NULL;")
        conn.commit()
        
        # Confirmar a atualizacao
        cursor.execute("SELECT COUNT(*) FROM users WHERE playground_connected = 1;")
        count_after = cursor.fetchone()[0]
        
        print(f"Sucesso em {db_path}:")
        print(f"  Usuarios conectados antes: {count_before}")
        print(f"  Usuarios conectados depois: {count_after}")
        conn.close()
    except Exception as e:
        print(f"Erro ao processar {db_path}: {e}")

if __name__ == "__main__":
    db_dev = "./backend/data/developer/automation_hub_dev.db"
    db_prod = "./backend/data/automation_hub_dev.db"
    
    # Se rodado a partir de backend/scripts, ajusta os caminhos relativos
    if os.path.basename(os.getcwd()) == "scripts":
        db_dev = "../data/developer/automation_hub_dev.db"
        db_prod = "../data/automation_hub_dev.db"
    elif os.path.basename(os.getcwd()) == "backend":
        db_dev = "./data/developer/automation_hub_dev.db"
        db_prod = "./data/automation_hub_dev.db"
        
    print("Iniciando reset de status do Playground nos bancos SQLite...")
    reset_db(db_dev)
    reset_db(db_prod)
    print("Processo concluido.")
