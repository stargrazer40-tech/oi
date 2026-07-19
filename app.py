import streamlit as st
import os
import wikipedia
import re
from groq import Groq

# ==========================================
# ☁️ CLOUD CONFIGURATION 
# ==========================================
CLOUD_MODEL = "llama-3.1-8b-instant"

if "GROQ_API_KEY" in st.secrets:
    api_key = st.secrets["GROQ_API_KEY"]
else:
    api_key = os.environ.get("GROQ_API_KEY")

if not api_key:
    st.error("🔒 Security Alert: GROQ_API_KEY environment token was not found on the cloud server.")
    st.stop()

client = Groq(api_key=api_key)

# ==========================================
# 🧮 SYSTEM TOOLS (CALCULATOR & WIKIPEDIA)
# ==========================================
def calculate_expression(expression):
    """Safely evaluates a mathematical expression string in the cloud"""
    try:
        sanitized = re.sub(r'[^0-9\+\-\*\/\(\)\.\s]', '', expression)
        if not sanitized.strip():
            return "Error: Invalid calculation expression input."
        result = eval(sanitized, {"__builtins__": None}, {})
        return f"🧮 Calculator Result: {expression} = {result}"
    except Exception as e:
        return f"Error evaluating math equation: {str(e)}"

def search_wikipedia(query):
    """Searches Wikipedia over the web and extracts a concise factual summary"""
    try:
        summary = wikipedia.summary(query, sentences=3, auto_suggest=True)
        return f"🌐 Wikipedia Entry for '{query}':\n\n{summary}"
    except wikipedia.exceptions.DisambiguationError as e:
        return f"Disambiguation Error: Multiple matches found for '{query}'. Specific options: {e.options[:5]}"
    except wikipedia.exceptions.PageError:
        return f"Error: No Wikipedia article matching '{query}' could be located."
    except Exception as e:
        return f"Error retrieving Wikipedia data: {str(e)}"

# ==========================================
# 🌌 CORE AGENT CORE ARCHITECTURE
# ==========================================
CORE_SYSTEM_PROMPT = (
    "You are the central OmniX Core AI. You are analytical, highly efficient, and direct. "
    "You have access to two functional backend tools to enhance your accuracy:\n"
    "1. Wikipedia Search: Use this tool to pull verified summaries for historical events, elements, or entities.\n"
    "2. Calculator: Use this tool to evaluate exact math equations and calculations.\n\n"
    "If a user asks a calculation or requests factual lookups, you should use the tool definitions."
)

def generate_agent_response(user_query, history_context):
    """Routes payloads directly to Cloud Engine with rule-based tool parsing"""
    lower_query = user_query.lower()
    
    if any(keyword in lower_query for keyword in ["calculate", "solve", "math", "compute", "+", "-", "*", "/"]):
        math_match = re.search(r'[\d\+\-\*\/\(\)\.\s]{3,}', user_query)
        if math_match:
            return calculate_expression(math_match.group(0))
            
    if any(keyword in lower_query for keyword in ["search for", "wikipedia", "lookup", "who is", "what is"]):
        search_target = re.sub(r'(search for|wikipedia|lookup|who is|what is)', '', lower_query).strip()
        if search_target:
            return search_wikipedia(search_target)

    messages = [{"role": "system", "content": CORE_SYSTEM_PROMPT}]
    for msg in history_context:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_query})
    
    completion = client.chat.completions.create(
        model=CLOUD_MODEL,
        messages=messages
    )
    return completion.choices[0].message.content

# ==========================================
# 💻 STREAMLIT CORE APPLICATION UI
# ==========================================
st.set_page_config(page_title="OmniX OS", page_icon="🛰️", layout="wide")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

st.title("🛰️ OmniX AI — Fully Cloud OS")
st.caption(f"Environment: ☁️ GROQ CLOUD REPO ({CLOUD_MODEL}) // Architecture: Serverless Tool Router")
st.markdown("---")

with st.sidebar:
    st.header("⚡ System Options")
    
    # 🟦 THE BLUE BLOCK: Your authorized public biography
    st.info(
        "**Saransh (Krish) — The Architect of Silence**\n\n"
        "**Origins:** Born in 2015, in Bihar, India, into a family with deep backgrounds in "
        "systems, software engineering, computer science education, administration, and law.\n\n"
        "**The Detective:** By the age of eleven, Saransh approaches complex informational puzzles "
        "not with guesswork, but with strict logic, adversarial pattern recognition, and an investigative mindset.\n\n"
        "**The Builder:** Operates under a philosophy of resource efficiency and practical execution: "
        "*'Let my actions speak. Words are cheap. Builds are forever.'*\n\n"
        "**Achievements:** 1st in school science rankings (97/100), competitive ranking in arts and spelling, "
        "and extensive development execution in custom coding languages."
    )
    
    if st.button("Reset Memory Core"):
        st.session_state.chat_history = []
        st.rerun()

for message in st.session_state.chat_history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if user_input := st.chat_input("Send command to OmniX Cloud Core..."):
    with st.chat_message("user"):
        st.markdown(user_input)
        
    with st.chat_message("assistant"):
        with st.spinner("Streaming from cloud matrix..."):
            try:
                ai_output = generate_agent_response(user_input, st.session_state.chat_history)
                st.markdown(ai_output)
                
                st.session_state.chat_history.append({"role": "user", "content": user_input})
                st.session_state.chat_history.append({"role": "assistant", "content": ai_output})
                
            except Exception as e:
                st.error(f"Cloud Execution Error: {str(e)}")
