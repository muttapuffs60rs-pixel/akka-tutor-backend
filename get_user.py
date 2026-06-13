import os
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()
supabase: Client = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
res = supabase.table("profiles").select("id").limit(1).execute()
if res.data:
    print(f"USER_ID_FOUND={res.data[0]['id']}")
else:
    print("NO_USERS_FOUND")
