import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(url, key)

def make_admin():
    target_email = "tester001@test.com"
    try:
        # First, let's list users from auth.admin
        response = supabase.auth.admin.list_users()
        users = response
        
        user_id = None
        for u in users:
            if u.email.lower() == target_email.lower():
                user_id = u.id
                break
                
        if user_id:
            res = supabase.table("profiles").update({"subscription_tier": "admin"}).eq("id", user_id).execute()
            print(f"Success! Updated user {target_email} (ID: {user_id}) to admin tier.")
        else:
            print(f"User {target_email} not found in auth.users.")
    except Exception as e:
        print(f"Admin API failed: {e}")
        # Fallback if profiles table has an email column
        print("Trying fallback via profiles table email column...")
        try:
            res = supabase.table("profiles").update({"subscription_tier": "admin"}).eq("email", target_email).execute()
            print(f"Fallback response: {res.data}")
        except Exception as e2:
            print(f"Fallback failed: {e2}")

if __name__ == "__main__":
    make_admin()
