import os
from supabase import create_client, Client

# 1. Put your specific keys here
url: str = "https://xhloiwzkoswtdmgwfoil.supabase.co"
key: str = "sb_publishable_xGuRAr3G-0Z4UF4FfNHbgQ_CUIhdwTt"

# 2. Connect to the vault
supabase: Client = create_client(url, key)

print("Connecting to the vault...")

# 3. Pull the questions from Unit 1
response = supabase.table('mock_questions').select('*').eq('unit_number', 1).execute()

# 4. Print what we found!
questions = response.data
print(f"SUCCESS! Found {len(questions)} questions in the database.\n")

# Show the very first question to prove it worked
if len(questions) > 0:
    print("Here is Question 1:")
    print(f"Q: {questions[0]['question_text']}")
    print(f"A: {questions[0]['option_a']}")
    print(f"B: {questions[0]['option_b']}")
    print(f"C: {questions[0]['option_c']}")
    print(f"D: {questions[0]['option_d']}")