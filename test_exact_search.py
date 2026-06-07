import os
import re
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

search_query = "explain 4.11.2 section"
section_match = re.search(r'\b(\d+\.\d+(?:\.\d+)?)\b', search_query)

if section_match:
    sec_num = section_match.group(1)
    print(f"Found section number: {sec_num}")
    
    # Supabase exact search
    res = supabase.table("documents").select("unit_name, section_name, sub_section_name, content") \
        .eq("grade_level", 10) \
        .eq("subject", "Science") \
        .or_(f"section_name.ilike.%{sec_num}%,sub_section_name.ilike.%{sec_num}%,content.ilike.%{sec_num}%") \
        .limit(3) \
        .execute()
        
    print(f"Found {len(res.data)} exact matches.")
    for d in res.data:
        print(f"[{d.get('unit_name')} -> {d.get('section_name')} -> {d.get('sub_section_name')}]")
        print(d.get('content')[:100])
