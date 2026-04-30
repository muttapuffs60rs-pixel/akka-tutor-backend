import google.generativeai as genai
import os

# 1. Setup your API Key
# Replace the text below with your actual key from Google AI Studio
API_KEY = "AIzaSyDojYAbdRvx6kj2pZ4osLlR15DQxnVvBHQ"
genai.configure(api_key=API_KEY)

def list_my_models():
    print("--- STARTING MODEL DISCOVERY ---")
    try:
        # 2. Ask Google for the list
        models = genai.list_models()
        
        found_any = False
        for m in models:
            # 3. Filter for models that can actually chat/generate text
            if 'generateContent' in m.supported_generation_methods:
                print(f"✅ VALID MODEL: {m.name}")
                found_any = True
        
        if not found_any:
            print("❌ No text-generation models found. Check if your API key is active.")
            
    except Exception as e:
        print(f"⚠️ ERROR CONNECTING TO GOOGLE: {e}")
    
    print("--- DISCOVERY FINISHED ---")

if __name__ == "__main__":
    list_my_models()