import streamlit as st
import requests
import os
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables for Supabase
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Set up the page (MUST be the first Streamlit command)
st.set_page_config(page_title="Akka AI Tutor", page_icon="👩‍🏫")

# --- 1. AUTHENTICATION GATE ---
if "user_id" not in st.session_state:
    st.title("🔐 Welcome to Akka AI")
    st.write("Please log in or sign up to start learning!")
    
    tab1, tab2 = st.tabs(["Log In", "Sign Up"])
    
    # LOGIN TAB
    with tab1:
        with st.form("login_form"):
            login_email = st.text_input("Email")
            login_password = st.text_input("Password", type="password")
            submit_login = st.form_submit_button("Log In")
            
            if submit_login:
                try:
                    response = supabase.auth.sign_in_with_password({"email": login_email, "password": login_password})
                    st.session_state.user_id = response.user.id
                    st.session_state.user_email = response.user.email
                    st.success("Logged in successfully!")
                    st.rerun() # Refreshes the page to show the chat app
                except Exception as e:
                    st.error("Login failed. Check your email and password.")
                    
    # SIGN UP TAB
    with tab2:
        with st.form("signup_form"):
            signup_name = st.text_input("Full Name (e.g., Dineshraj)")
            signup_email = st.text_input("Email")
            signup_password = st.text_input("Password", type="password")
            submit_signup = st.form_submit_button("Sign Up")
            
            if submit_signup:
                try:
                    # Notice we pass the full_name here so your SQL Trigger catches it!
                    response = supabase.auth.sign_up({
                        "email": signup_email, 
                        "password": signup_password,
                        "options": {
                            "data": {"full_name": signup_name}
                        }
                    })
                    st.session_state.user_id = response.user.id
                    st.session_state.user_email = response.user.email
                    st.success("Account created successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Sign up failed: {e}")

# --- 2. MAIN APP (Only runs if logged in) ---
else:
    st.title("👩‍🏫 Akka AI - Samacheer Kalvi Tutor")

    # Sidebar with Logout Button and Selectors (Kept from old code!)
    with st.sidebar:
        st.header("Student Profile")
        st.write(f"👤 **{st.session_state.user_email}**")
        
        if st.button("Log Out"):
            st.session_state.clear() # Wipes the memory
            st.rerun()
            
        st.divider()
        grade = st.selectbox("Grade", [6, 7, 8, 9, 10, 11, 12], index=4)
        subject = st.selectbox("Subject", ["Science", "Maths", "Social Science"])

    # Initialize chat history
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Vanakkam Kanna! Enna subject padikalam iniku? 😊"}]

    # Display chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # React to user input
    if prompt := st.chat_input("Ask Akka a question..."):
        st.chat_message("user").markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})

        is_first = len(st.session_state.messages) == 2 

        # Call FastAPI
        with st.spinner('Akka is thinking...'):
            try:
                response = requests.post(
                    "http://127.0.0.1:8000/ask", 
                    json={
                        "user_id": st.session_state.user_id, # <-- PERFECTLY INTEGRATED!
                        "question": prompt,
                        "grade_level": grade,
                        "subject": subject,
                        "is_first_message": is_first,
                        "history": st.session_state.messages[-4:] 
                    }
                )
                
                if response.status_code == 200:
                    akka_reply = response.json()["answer"]
                else:
                    akka_reply = f"Sorry kanna, server error. (Code: {response.status_code})"
                    
            except Exception as e:
                akka_reply = "API connect aagala thambi. Make sure FastAPI is running!"

        # Display assistant message
        with st.chat_message("assistant"):
            st.markdown(akka_reply)
            
        st.session_state.messages.append({"role": "assistant", "content": akka_reply})