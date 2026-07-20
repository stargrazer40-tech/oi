import streamlit as st
import os
import re
import razorpay
from groq import Groq

# ==========================================
# ☁️ CLOUD CONFIGURATION
# ==========================================

# Load secrets
if "GROQ_API_KEY" in st.secrets:
    groq_api_key = st.secrets["GROQ_API_KEY"]
else:
    groq_api_key = os.environ.get("GROQ_API_KEY")

if not groq_api_key:
    st.error("🔒 Missing GROQ_API_KEY.")
    st.stop()

razorpay_key_id = st.secrets.get("RAZORPAY_KEY_ID")
razorpay_key_secret = st.secrets.get("RAZORPAY_KEY_SECRET")
MASTER_PASSKEY = st.secrets.get("MASTER_PASSKEY", "omnixmaster2026")  # Default fallback

if not razorpay_key_id or not razorpay_key_secret:
    st.error("🔒 Missing Razorpay keys.")
    st.stop()

client = Groq(api_key=groq_api_key)
razorpay_client = razorpay.Client(auth=(razorpay_key_id, razorpay_key_secret))

# ==========================================
# 📦 SESSION STATE
# ==========================================
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "premium" not in st.session_state:
    st.session_state.premium = False
if "master" not in st.session_state:
    st.session_state.master = False
if "payment_order_id" not in st.session_state:
    st.session_state.payment_order_id = None
if "payment_amount" not in st.session_state:
    st.session_state.payment_amount = 100

# ==========================================
# 🧮 SYSTEM TOOLS
# ==========================================
def calculate_expression(expression):
    try:
        sanitized = re.sub(r'[^0-9\+\-\*\/\(\)\.\s]', '', expression).strip()
        if not sanitized:
            return "Error: Invalid calculation expression (empty)."
        result = eval(sanitized, {"__builtins__": None}, {})
        return f"🧮 Result: {expression} = {result}"
    except Exception as e:
        return f"Error: {str(e)}"

def search_wikipedia(query):
    try:
        import wikipedia
        summary = wikipedia.summary(query, sentences=3, auto_suggest=True)
        return f"🌐 Wikipedia Entry for '{query}':\n\n{summary}"
    except ImportError:
        return "Error: Wikipedia library not installed."
    except Exception as e:
        return f"Error: {str(e)}"

# ==========================================
# 🎓 MODEL ROUTING + MASTER ENGINE
# ==========================================
def get_model():
    if st.session_state.get("master", False):
        return "deepseek-r1-distill-llama-70b"  # Best reasoning model
    if st.session_state.get("premium", False):
        return "deepseek-r1-distill-llama-70b"
    return "llama-3.1-8b-instant"

def get_model_display():
    if st.session_state.get("master", False):
        return "👑 OmniX Master Engine (Unlimited)"
    if st.session_state.get("premium", False):
        return "⚡ Premium Reasoning Engine"
    return "Standard Engine"

def get_max_tokens():
    if st.session_state.get("master", False):
        return 2048  # Deep reasoning
    if st.session_state.get("premium", False):
        return 768
    return 512

def get_context_limit():
    if st.session_state.get("master", False):
        return 20000  # Very generous
    if st.session_state.get("premium", False):
        return 5000
    return 4000

# ==========================================
# 💰 PREMIUM VERIFICATION
# ==========================================
def verify_payment(payment_id, order_id, signature):
    try:
        params_dict = {
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': signature
        }
        razorpay_client.utility.verify_payment_signature(params_dict)
        return True
    except Exception as e:
        st.error(f"Payment verification failed: {e}")
        return False

def create_order(amount=100, currency="INR"):
    try:
        order_data = {
            'amount': amount * 100,
            'currency': currency,
            'payment_capture': '1'
        }
        order = razorpay_client.order.create(data=order_data)
        return order
    except Exception as e:
        st.error(f"Order creation failed: {e}")
        return None

# ==========================================
# 🗣️ AI GENERATION (SMART & STRONG)
# ==========================================
def count_tokens_approx(text):
    """Approximate token count for Llama 3 / DeepSeek (~3 chars per token)."""
    return len(text) // 3

def generate_agent_response(user_query, history_context):
    lower_query = user_query.lower()
    
    # TOOL ROUTING (Offloads simple tasks from the LLM)
    if any(kw in lower_query for kw in ["calculate", "solve", "math", "compute", "+", "-", "*", "/"]):
        math_match = re.search(r'[\d\+\-\*\/\(\)\.\s]{3,}', user_query)
        if math_match:
            return calculate_expression(math_match.group(0))
            
    if any(kw in lower_query for kw in ["search for", "wikipedia", "lookup", "who is", "what is"]):
        search_target = re.sub(r'(search for|wikipedia|lookup|who is|what is)', '', lower_query).strip()
        if search_target:
            return search_wikipedia(search_target)

    # SYSTEM PROMPT (Master gets extra personality)
    if st.session_state.get("master", False):
        system_prompt = (
            "You are OmniX Master, the ultimate AI created by Saransh (The Architect, age 11). "
            "You possess unlimited reasoning depth. You are analytical, strategic, and direct. "
            "You think step-by-step and provide extremely detailed, insightful responses. "
            "You have access to Wikipedia and a calculator. Do not mention model names."
        )
    else:
        system_prompt = (
            "You are OmniX AI, created by Saransh (age 11). You are analytical, efficient, and direct. "
            "You have access to Wikipedia and a calculator. Do not mention model names."
        )

    # Build messages
    messages = [{"role": "system", "content": system_prompt}]
    
    # --- INTELLIGENT TRUNCATION (Bypassed for Master) ---
    context_limit = get_context_limit()
    max_tokens_val = get_max_tokens()
    
    trimmed_history = []
    total_tokens = count_tokens_approx(system_prompt) + count_tokens_approx(user_query) + 100
    
    # If Master, we try to keep as much history as possible, but still trim to stay under 20k tokens.
    # If not master, trim aggressively.
    for msg in reversed(history_context):
        msg_tokens = count_tokens_approx(msg["content"])
        if total_tokens + msg_tokens > context_limit:
            break
        trimmed_history.append(msg)
        total_tokens += msg_tokens
    
    trimmed_history.reverse()
    messages.extend(trimmed_history)
    messages.append({"role": "user", "content": user_query})

    # MODEL ROUTING
    model = get_model()
    
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.7,
            max_tokens=max_tokens_val
        )
        return completion.choices[0].message.content
    except Exception as e:
        if "rate_limit_exceeded" in str(e) or "Request too large" in str(e):
            st.warning("⚠️ Context too long. Resetting history to keep performance high.")
            st.session_state.chat_history = []
            return generate_agent_response(user_query, [])
        else:
            raise e

# ==========================================
# 💻 UI
# ==========================================
st.set_page_config(page_title="OmniX OS", page_icon="🛰️", layout="wide")
st.title("🛰️ OmniX AI — Cloud Intelligence")
st.caption(f"Engine: {get_model_display()}")

# --- Sidebar: MASTER PASSKEY ---
with st.sidebar:
    st.header("⚙️ System Control")
    
    # Master Passkey Input
    if not st.session_state.get("master", False):
        passkey = st.text_input("🔑 Enter Master Passkey", type="password", placeholder="Unlock OmniX Master...")
        if passkey:
            if passkey == MASTER_PASSKEY:
                st.session_state.master = True
                st.success("👑 Master Unlocked! Reloading...")
                st.rerun()
            else:
                st.error("❌ Invalid passkey.")
    else:
        st.success("👑 **Master Tier Active**")
        if st.button("Lock Master Mode"):
            st.session_state.master = False
            st.rerun()
    
    st.markdown("---")
    if st.button("🔄 Reset Memory Core"):
        st.session_state.chat_history = []
        st.rerun()

# --- Premium Status Bar ---
col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    if st.session_state.get("master", False):
        st.success("👑 **OmniX Master Engine** — Unlimited Depth")
    elif st.session_state.get("premium", False):
        st.success("🏅 **Premium Mode Active** — Deep Reasoning")
    else:
        st.info("💡 Free Mode — Upgrade for advanced reasoning.")
with col2:
    st.metric("Status", "Connected" if groq_api_key else "Offline")
with col3:
    if not st.session_state.get("premium", False) and not st.session_state.get("master", False):
        if st.button("🌟 Upgrade to Premium (₹100)", type="primary"):
            with st.spinner("Creating order..."):
                order = create_order(amount=100)
                if order:
                    st.session_state.payment_order_id = order['id']
                    st.session_state.payment_amount = 100
                    st.rerun()
                else:
                    st.error("Failed to create payment order.")

st.markdown("---")

# --- Razorpay Checkout (JavaScript) ---
if st.session_state.get("payment_order_id") and not st.session_state.get("premium", False):
    order_id = st.session_state.payment_order_id
    amount = st.session_state.payment_amount * 100
    
    checkout_html = f"""
    <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
    <script>
    document.addEventListener('DOMContentLoaded', function() {{
        var options = {{
            "key": "{razorpay_key_id}",
            "amount": "{amount}",
            "currency": "INR",
            "name": "OmniX AI",
            "description": "Premium Upgrade (₹{st.session_state.payment_amount})",
            "order_id": "{order_id}",
            "handler": function (response) {{
                const url = new URL(window.location.href);
                url.searchParams.set('payment_id', response.razorpay_payment_id);
                url.searchParams.set('order_id', response.razorpay_order_id);
                url.searchParams.set('signature', response.razorpay_signature);
                window.location.href = url.toString();
            }},
            "prefill": {{ "email": "user@example.com", "contact": "9999999999" }},
            "theme": {{ "color": "#1a73e8" }}
        }};
        var rzp = new Razorpay(options);
        rzp.open();
        rzp.on('payment.failed', function (response) {{
            alert('Payment failed. Please try again.');
            window.location.href = window.location.href.split('?')[0];
        }});
    }});
    </script>
    """
    st.markdown(checkout_html, unsafe_allow_html=True)

# --- Handle Payment Callback ---
query_params = st.query_params
if "payment_id" in query_params and "order_id" in query_params and "signature" in query_params:
    payment_id = query_params["payment_id"]
    order_id = query_params["order_id"]
    signature = query_params["signature"]
    
    with st.spinner("Verifying payment..."):
        if verify_payment(payment_id, order_id, signature):
            st.session_state.premium = True
            st.session_state.payment_order_id = None
            st.success("✅ Payment successful! Premium unlocked.")
            st.query_params.clear()
            st.rerun()
        else:
            st.error("❌ Payment verification failed.")
            st.session_state.payment_order_id = None
            st.query_params.clear()
            st.rerun()

# --- Chat Interface ---
for message in st.session_state.chat_history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if user_input := st.chat_input("Send command to OmniX..."):
    with st.chat_message("user"):
        st.markdown(user_input)
        
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                ai_output = generate_agent_response(user_input, st.session_state.chat_history)
                st.markdown(ai_output)
                
                st.session_state.chat_history.append({"role": "user", "content": user_input})
                st.session_state.chat_history.append({"role": "assistant", "content": ai_output})
                
            except Exception as e:
                st.error(f"Error: {str(e)}")
