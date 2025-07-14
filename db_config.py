import mariadb
import os
from dotenv import load_dotenv

load_dotenv()

def get_connection() :
    return mariadb.connect(host=os.getenv("DB_HOST"),user=os.getenv("DB_USER"),password=os.getenv("DB_PASS"),
                           database=os.getenv("DB_NAME"),port=int(os.getenv("DB_PORT")))