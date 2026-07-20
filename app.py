import streamlit as st
import os
import re
import json
import time
import razorpay
from groq import Groq
import chromadb
from chromadb.utils import embedding_functions

# ─────────────────────────────────────────────────────────────
# ☁️ CLOUD CONFIGURATION
# ─────────────────────────────────────────────────────────────

if "GROQ_API_KEY" in st.secrets:
    groq_api_key = st.secrets["GROQ_API_KEY"]
else:
    groq_api_key = os.environ.get("GROQ_API_KEY")

if not groq_api_key:
    st.error("🔒 Missing GROQ_API_KEY.")
    st.stop()

razorpay_key_id = st.secrets.get("RAZORPAY_KEY_ID")
razorpay_key_secret = st.secrets.get("RAZORPAY_KEY_SECRET")
MASTER_PASSKEY = st.secrets.get("MASTER_PASSKEY", "rengoku")

if not razorpay_key_id or not razorpay_key_secret:
    st.error("🔒 Missing Razorpay keys.")
    st.stop()

client = Groq(api_key=groq_api_key)
razorpay_client = razorpay.Client(auth=(razorpay_key_id, razorpay_key_secret))

# ─────────────────────────────────────────────────────────────
# 📦 SESSION STATE
# ─────────────────────────────────────────────────────────────

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
if "current_conversation_id" not in st.session_state:
    st.session_state.current_conversation_id = None

# ─────────────────────────────────────────────────────────────
# 🧠 CHROMADB SETUP
# ─────────────────────────────────────────────────────────────

CHROMA_PATH = "universa_chroma_db"
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
embedding_fn = embedding_functions.DefaultEmbeddingFunction()

try:
    conv_collection = chroma_client.get_collection("conversations")
except:
    conv_collection = chroma_client.create_collection(
        name="conversations",
        embedding_function=embedding_fn
    )

try:
    memory_collection = chroma_client.get_collection("chat_memory")
except:
    memory_collection = chroma_client.create_collection(
        name="chat_memory",
        embedding_function=embedding_fn
    )

# ─────────────────────────────────────────────────────────────
# 💾 CONVERSATION CRUD (ChromaDB)
# ─────────────────────────────────────────────────────────────

def save_conversation(conv_id, messages, title=None):
    if not messages:
        return
    if not title:
        title = messages[0]["content"][:30] + "..." if messages else "New Chat"
    messages_json = json.dumps(messages)
    conv_collection.upsert(
        ids=[conv_id],
        documents=[messages_json],
        metadatas=[{
            "title": title,
            "timestamp": time.time(),
            "message_count": len(messages)
        }]
    )

def load_conversation(conv_id):
    try:
        result = conv_collection.get(ids=[conv_id])
        if result and result['documents']:
            return json.loads(result['documents'][0])
    except:
        pass
    return None

def delete_conversation(conv_id):
    try:
        conv_collection.delete(ids=[conv_id])
    except:
        pass

def get_all_conversations(limit=100):
    try:
        result = conv_collection.get(limit=limit)
        if result and result['ids']:
            convs = []
            for idx, conv_id in enumerate(result['ids']):
                metadata = result['metadatas'][idx]
                convs.append({
                    "id": conv_id,
                    "title": metadata.get("title", "Untitled"),
                    "timestamp": metadata.get("timestamp", 0),
                    "message_count": metadata.get("message_count", 0)
                })
            convs.sort(key=lambda x: x["timestamp"], reverse=True)
            return convs
    except:
        pass
    return []

def get_conversation_groups():
    convs = get_all_conversations()
    now = time.time()
    today = now - 86400
    week = now - 604800
    month = now - 2592000
    
    groups = {"Today": [], "7 Days": [], "30 Days": [], "Older": []}
    
    for conv in convs:
        ts = conv["timestamp"]
        title = conv["title"]
        conv_id = conv["id"]
        if ts >= today:
            groups["Today"].append((conv_id, title, ts))
        elif ts >= week:
            groups["7 Days"].append((conv_id, title, ts))
        elif ts >= month:
            groups["30 Days"].append((conv_id, title, ts))
        else:
            groups["Older"].append((conv_id, title, ts))
    
    for key in groups:
        groups[key].sort(key=lambda x: x[2], reverse=True)
    
    return groups

def save_current_conversation():
    if st.session_state.chat_history and st.session_state.current_conversation_id:
        save_conversation(
            st.session_state.current_conversation_id,
            st.session_state.chat_history
        )

def new_conversation():
    save_current_conversation()
    st.session_state.chat_history = []
    st.session_state.current_conversation_id = str(int(time.time()))
    st.rerun()

def load_conversation_by_id(conv_id):
    messages = load_conversation(conv_id)
    if messages is not None:
        st.session_state.chat_history = messages
        st.session_state.current_conversation_id = conv_id
        st.rerun()

# ─────────────────────────────────────────────────────────────
# 🧮 SYSTEM TOOLS
# ─────────────────────────────────────────────────────────────

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

# ─────────────────────────────────────────────────────────────
# 🎓 MODEL ROUTING + MASTER ENGINE
# ─────────────────────────────────────────────────────────────

FREE_MODEL = "llama-3.1-8b-instant"
PREMIUM_MODEL = "llama-3.3-70b-versatile"

def get_model():
    if st.session_state.get("master", False) or st.session_state.get("premium", False):
        return PREMIUM_MODEL
    return FREE_MODEL

def get_model_display():
    if st.session_state.get("master", False):
        return "👑 Universa Master (70B Reasoning + Memory)"
    if st.session_state.get("premium", False):
        return "⚡ Universa Premium (70B Reasoning + Memory)"
    return "Universa Standard Engine"

def get_max_tokens():
    if st.session_state.get("master", False) or st.session_state.get("premium", False):
        return 4096
    return 512

def get_context_limit():
    if st.session_state.get("master", False) or st.session_state.get("premium", False):
        return 120000
    return 4000

# ─────────────────────────────────────────────────────────────
# 💰 PREMIUM VERIFICATION
# ─────────────────────────────────────────────────────────────

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

# ─────────────────────────────────────────────────────────────
# 🗣️ AI GENERATION (WITH VECTOR MEMORY + SILENT TRIMMING)
# ─────────────────────────────────────────────────────────────

def count_tokens_approx(text):
    return len(text) // 4   # Llama 3 ~4 chars per token

def generate_agent_response(user_query, history_context):
    lower_query = user_query.lower()
    
    # TOOL ROUTING
    if any(kw in lower_query for kw in ["calculate", "solve", "math", "compute", "+", "-", "*", "/"]):
        math_match = re.search(r'[\d\+\-\*\/\(\)\.\s]{3,}', user_query)
        if math_match:
            return calculate_expression(math_match.group(0))
            
    if any(kw in lower_query for kw in ["search for", "wikipedia", "lookup", "who is", "what is"]):
        search_target = re.sub(r'(search for|wikipedia|lookup|who is|what is)', '', lower_query).strip()
        if search_target:
            return search_wikipedia(search_target)

    # ── VECTOR MEMORY RETRIEVAL (Premium/Master only) ──
    memory_context = ""
    if st.session_state.get("premium", False) or st.session_state.get("master", False):
        try:
            results = memory_collection.query(
                query_texts=[user_query],
                n_results=5
            )
            if results and results['documents']:
                mems = []
                for doc, meta in zip(results['documents'][0], results['metadatas'][0]):
                    mems.append(f"[{meta.get('role','')}]: {doc[:500]}")
                if mems:
                    memory_context = "=== RETRIEVED MEMORIES ===\n" + "\n".join(mems) + "\n=== END ===\n"
        except:
            pass

    # ── SYSTEM PROMPT ──
    if st.session_state.get("master", False):
        system_prompt = (
            "You are Universa Master – the ultimate AI created by Saransh (The Architect, age 11). "
            "You possess deep reasoning abilities. You are analytical, strategic, and direct. "
            "Think step-by-step and provide extremely detailed, insightful responses. "
            "You have access to Wikipedia and a calculator. Never mention model names."
        )
    elif st.session_state.get("premium", False):
        system_prompt = (
            "You are Universa Premium – an advanced AI built by Saransh (The Architect, age 11). "
            "You are a powerful reasoning engine. Be clear, precise, and helpful. "
            "You have access to Wikipedia and a calculator. Do not mention model names."
        )
    else:
        system_prompt = (
            "You are Universa AI, created by Saransh (age 11). You are analytical, efficient, and direct. "
            "You have access to Wikipedia and a calculator. Do not mention model names."
        )

    if memory_context:
        system_prompt = memory_context + "\n" + system_prompt

    # ── BUILD MESSAGES WITH INTELLIGENT TRIMMING (NO WARNINGS) ──
    messages = [{"role": "system", "content": system_prompt}]
    
    context_limit = get_context_limit()
    max_tokens_val = get_max_tokens()
    
    # Start with system + user query
    base_tokens = count_tokens_approx(system_prompt) + count_tokens_approx(user_query) + 50
    total_tokens = base_tokens
    trimmed_history = []
    
    # Keep as many recent messages as possible, drop oldest if limit exceeded
    for msg in reversed(history_context):
        msg_tokens = count_tokens_approx(msg["content"])
        if total_tokens + msg_tokens > context_limit:
            break
        trimmed_history.append(msg)
        total_tokens += msg_tokens
    
    trimmed_history.reverse()
    messages.extend(trimmed_history)
    messages.append({"role": "user", "content": user_query})

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
        # If still too long, aggressively trim to last 4 messages + query
        if "rate_limit_exceeded" in str(e) or "Request too large" in str(e):
            if len(history_context) > 4:
                st.session_state.chat_history = history_context[-4:]   # keep last 4
            else:
                st.session_state.chat_history = []
            return generate_agent_response(user_query, st.session_state.chat_history)
        else:
            raise e

# ─────────────────────────────────────────────────────────────
# 💻 UI
# ─────────────────────────────────────────────────────────────

st.set_page_config(page_title="Universa OS", page_icon="🛰️", layout="wide")
st.title("🛰️ Universa AI — Cloud Intelligence")

with st.sidebar:
    st.caption(f"Engine: {get_model_display()}")
    st.markdown("---")
    
    if st.button("✏️ New Chat", use_container_width=True):
        new_conversation()
    
    st.markdown("---")
    
    st.subheader("📋 Chat History")
    groups = get_conversation_groups()
    for group_name, convs in groups.items():
        if convs:
            st.markdown(f"**{group_name}**")
            for conv_id, title, ts in convs:
                col1, col2 = st.columns([0.85, 0.15])
                with col1:
                    if st.button(f"{title}", key=f"load_{conv_id}", use_container_width=True):
                        load_conversation_by_id(conv_id)
                with col2:
                    if st.button("✕", key=f"del_{conv_id}"):
                        delete_conversation(conv_id)
                        st.rerun()
            st.markdown("---")
    
    st.markdown("---")
    st.subheader("🔑 Master Access")
    if not st.session_state.get("master", False):
        passkey = st.text_input("Enter Master Passkey", type="password", placeholder="Unlock Universa Master...")
        if passkey:
            if passkey == MASTER_PASSKEY:
                st.session_state.master = True
                st.success("👑 Master Unlocked!")
                st.rerun()
            else:
                st.error("❌ Invalid passkey.")
    else:
        st.success("👑 **Master Tier Active**")
        if st.button("Lock Master Mode"):
            st.session_state.master = False
            st.rerun()
    
    st.markdown("---")
    if st.button("🧹 Clear All Memory", use_container_width=True):
        try:
            chroma_client.delete_collection("conversations")
            chroma_client.delete_collection("chat_memory")
            # Recreate collections
            conv_collection = chroma_client.create_collection("conversations", embedding_function=embedding_fn)
            memory_collection = chroma_client.create_collection("chat_memory", embedding_function=embedding_fn)
            st.session_state.chat_history = []
            st.session_state.current_conversation_id = None
            st.success("✅ All memory cleared!")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to clear memory: {e}")

# ── STATUS BAR ──
col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    if st.session_state.get("master", False):
        st.success("👑 **Universa Master (70B + Memory)**")
    elif st.session_state.get("premium", False):
        st.success("🏅 **Universa Premium (70B + Memory)**")
    else:
        st.info("💡 Free Mode — Upgrade for memory + advanced reasoning.")
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

# ── RAZORPAY CHECKOUT ──
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
            "name": "Universa AI",
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

# ── PAYMENT CALLBACK ──
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

# ── CHAT INTERFACE ──
for message in st.session_state.chat_history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if user_input := st.chat_input("Send command to Universa..."):
    save_current_conversation()
    
    with st.chat_message("user"):
        st.markdown(user_input)
        
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                ai_output = generate_agent_response(user_input, st.session_state.chat_history)
                st.markdown(ai_output)
                
                st.session_state.chat_history.append({"role": "user", "content": user_input})
                st.session_state.chat_history.append({"role": "assistant", "content": ai_output})
                
                # Store individual messages in vector memory (Premium/Master only)
                if st.session_state.get("premium", False) or st.session_state.get("master", False):
                    try:
                        memory_collection.add(
                            documents=[user_input],
                            metadatas=[{"role": "user", "timestamp": time.time()}],
                            ids=[f"{int(time.time())}_{hash(user_input)}"]
                        )
                        memory_collection.add(
                            documents=[ai_output],
                            metadatas=[{"role": "assistant", "timestamp": time.time()}],
                            ids=[f"{int(time.time())}_{hash(ai_output)}"]
                        )
                    except:
                        pass
                
                save_current_conversation()
                
            except Exception as e:
                st.error(f"Error: {str(e)}")
