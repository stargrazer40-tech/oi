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

if not razorpay_key_id or not razorpay_key_secret:
    st.error("🔒 Missing Razorpay keys. Please set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in secrets.")
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
if "payment_order_id" not in st.session_state:
    st.session_state.payment_order_id = None
if "payment_amount" not in st.session_state:
    st.session_state.payment_amount = 100

# ==========================================
# 🧮 SYSTEM TOOLS
# ==========================================
def calculate_expression(expression):
    try:
        # Sanitize input: allow only numbers, operators, parentheses, dot, and space
        sanitized = re.sub(r'[^0-9\+\-\*\/\(\)\.\s]', '', expression).strip()
        if not sanitized:
            return "Error: Invalid calculation expression (empty)."
        # Safely evaluate using restricted globals
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
# 🎓 MODEL ROUTING (HIDDEN FROM USER)
# ==========================================
def get_model():
    if st.session_state.get("premium", False):
        return "deepseek-r1-distill-llama-70b"  # Groq's best reasoning model
    return "llama-3.1-8b-instant"

def get_model_display():
    if st.session_state.get("premium", False):
        return "⚡ Premium Reasoning Engine"
    return "Standard Engine"

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
            'amount': amount * 100,  # Razorpay uses paise
            'currency': currency,
            'payment_capture': '1'
        }
        order = razorpay_client.order.create(data=order_data)
        return order
    except Exception as e:
        st.error(f"Order creation failed: {e}")
        return None

# ==========================================
# 🗣️ AI GENERATION
# ==========================================
def generate_agent_response(user_query, history_context):
    lower_query = user_query.lower()
    
    # Tool routing
    if any(kw in lower_query for kw in ["calculate", "solve", "math", "compute", "+", "-", "*", "/"]):
        math_match = re.search(r'[\d\+\-\*\/\(\)\.\s]{3,}', user_query)
        if math_match:
            return calculate_expression(math_match.group(0))
            
    if any(kw in lower_query for kw in ["search for", "wikipedia", "lookup", "who is", "what is"]):
        search_target = re.sub(r'(search for|wikipedia|lookup|who is|what is)', '', lower_query).strip()
        if search_target:
            return search_wikipedia(search_target)

    # System prompt - no model names exposed
    system_prompt = (
        "You are OmniX AI. You were created by an 11-year-old boy named Saransh. "
        "You are analytical, highly efficient, and direct. "
        "You have access to Wikipedia search and a calculator. Respond clearly. "
        "Never mention the model name, version, or internal architecture."
    )
    
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history_context:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_query})
    
    model = get_model()
    
    completion = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.7,
        max_tokens=1024
    )
    return completion.choices[0].message.content

# ==========================================
# 💻 UI
# ==========================================
st.set_page_config(page_title="OmniX OS", page_icon="🛰️", layout="wide")
st.title("🛰️ OmniX AI — Cloud Intelligence")
st.caption(f"Engine: {get_model_display()}")

# --- Premium Status Bar ---
col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    if st.session_state.get("premium", False):
        st.success("🏅 **Premium Mode Active** — Deep Reasoning Engine")
    else:
        st.info("💡 Free Mode — Upgrade for advanced reasoning.")
with col2:
    st.metric("Status", "Connected" if groq_api_key else "Offline")
with col3:
    if not st.session_state.get("premium", False):
        if st.button("🌟 Upgrade to Premium (₹100)", type="primary"):
            with st.spinner("Creating order..."):
                order = create_order(amount=100)
                if order:
                    st.session_state.payment_order_id = order['id']
                    st.session_state.payment_amount = 100
                    st.rerun()
                else:
                    st.error("Failed to create payment order. Please try again.")

st.markdown("---")

# --- Razorpay Checkout (JavaScript via markdown) ---
if st.session_state.get("payment_order_id") and not st.session_state.get("premium", False):
    order_id = st.session_state.payment_order_id
    amount = st.session_state.payment_amount * 100  # paise
    
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
                // Redirect back to app with payment details in URL
                var data = {{
                    payment_id: response.razorpay_payment_id,
                    order_id: response.razorpay_order_id,
                    signature: response.razorpay_signature
                }};
                const url = new URL(window.location.href);
                url.searchParams.set('payment_id', data.payment_id);
                url.searchParams.set('order_id', data.order_id);
                url.searchParams.set('signature', data.signature);
                window.location.href = url.toString();
            }},
            "prefill": {{
                "email": "user@example.com",
                "contact": "9999999999"
            }},
            "theme": {{
                "color": "#1a73e8"
            }}
        }};
        var rzp = new Razorpay(options);
        rzp.open();
        rzp.on('payment.failed', function (response) {{
            alert('Payment failed. Please try again.');
            // Clear order_id from session and reload
            const url = new URL(window.location.href);
            url.searchParams.delete('order_id');
            window.location.href = url.toString();
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
            # Remove query params from URL
            st.query_params.clear()
            st.rerun()
        else:
            st.error("❌ Payment verification failed. Please contact support.")
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
