from flask import Flask, request, jsonify, render_template, session
import os
import json
import time
import re
import razorpay
from groq import Groq
import chromadb
from chromadb.utils import embedding_functions
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.urandom(24)

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

GROQ_API_KEY = os.environ.get("GROQ_API_KEY") or "your_groq_key"
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID") or "rzp_test_xxx"
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET") or "your_secret"
MASTER_PASSKEY = os.environ.get("MASTER_PASSKEY") or "rengoku"

client = Groq(api_key=GROQ_API_KEY)
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# ─────────────────────────────────────────────────────────────
# CHROMADB
# ─────────────────────────────────────────────────────────────

CHROMA_PATH = "universa_chroma_db"
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
embedding_fn = embedding_functions.DefaultEmbeddingFunction()

try:
    conv_collection = chroma_client.get_collection("conversations")
except:
    conv_collection = chroma_client.create_collection("conversations", embedding_function=embedding_fn)

try:
    memory_collection = chroma_client.get_collection("chat_memory")
except:
    memory_collection = chroma_client.create_collection("chat_memory", embedding_function=embedding_fn)

# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def count_tokens(text):
    return len(text) // 4

def calculate_expression(expr):
    try:
        sanitized = re.sub(r'[^0-9\+\-\*\/\(\)\.\s]', '', expr).strip()
        if not sanitized:
            return "Error: Invalid expression"
        result = eval(sanitized, {"__builtins__": None}, {})
        return f"Result: {expr} = {result}"
    except Exception as e:
        return f"Error: {e}"

def search_wikipedia(query):
    try:
        import wikipedia
        summary = wikipedia.summary(query, sentences=3, auto_suggest=True)
        return f"Wikipedia: {summary}"
    except:
        return "Wikipedia: No results found."

def get_model(premium=False, master=False):
    if premium or master:
        return "llama-3.3-70b-versatile"
    return "llama-3.1-8b-instant"

def get_max_tokens(premium=False, master=False):
    if premium or master:
        return 4096
    return 512

def get_context_limit(premium=False, master=False):
    if premium or master:
        return 120000
    return 4000

def generate_response(user_query, history, premium=False, master=False):
    lower = user_query.lower()
    
    # Tool routing
    if any(k in lower for k in ["calculate", "solve", "math", "+", "-", "*", "/"]):
        match = re.search(r'[\d\+\-\*\/\(\)\.\s]{3,}', user_query)
        if match:
            return calculate_expression(match.group(0))
    
    if any(k in lower for k in ["wikipedia", "search for", "who is", "what is"]):
        target = re.sub(r'(wikipedia|search for|who is|what is)', '', lower).strip()
        if target:
            return search_wikipedia(target)

    # Vector memory retrieval (premium/master only)
    memory_context = ""
    if premium or master:
        try:
            results = memory_collection.query(query_texts=[user_query], n_results=5)
            if results and results['documents']:
                mems = []
                for doc, meta in zip(results['documents'][0], results['metadatas'][0]):
                    mems.append(f"[{meta.get('role','')}]: {doc[:500]}")
                if mems:
                    memory_context = "=== RETRIEVED MEMORIES ===\n" + "\n".join(mems) + "\n=== END ===\n"
        except:
            pass

    # System prompt
    if master:
        system_prompt = (
            "You are Universa Master – the ultimate AI created by Saransh (The Architect, age 11). "
            "You possess deep reasoning abilities. Think step-by-step. Never mention model names."
        )
    elif premium:
        system_prompt = (
            "You are Universa Premium – an advanced AI built by Saransh (The Architect, age 11). "
            "You are a powerful reasoning engine. Do not mention model names."
        )
    else:
        system_prompt = (
            "You are Universa AI, created by Saransh (age 11). You are analytical and direct. "
            "Do not mention model names."
        )

    if memory_context:
        system_prompt = memory_context + "\n" + system_prompt

    messages = [{"role": "system", "content": system_prompt}]
    
    context_limit = get_context_limit(premium, master)
    max_tokens = get_max_tokens(premium, master)
    
    # Trim history
    trimmed = []
    total = count_tokens(system_prompt) + count_tokens(user_query) + 50
    for msg in reversed(history):
        msg_tokens = count_tokens(msg["content"])
        if total + msg_tokens > context_limit:
            break
        trimmed.append(msg)
        total += msg_tokens
    
    trimmed.reverse()
    messages.extend(trimmed)
    messages.append({"role": "user", "content": user_query})

    model = get_model(premium, master)
    
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.7,
            max_tokens=max_tokens
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Error: {e}"

# ─────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json
    user_input = data.get('message', '')
    history = data.get('history', [])
    premium = data.get('premium', False)
    master = data.get('master', False)
    
    response = generate_response(user_input, history, premium, master)
    
    # Store in memory (premium/master only)
    if premium or master:
        try:
            memory_collection.add(
                documents=[user_input],
                metadatas=[{"role": "user", "timestamp": time.time()}],
                ids=[f"{int(time.time())}_{hash(user_input)}"]
            )
            memory_collection.add(
                documents=[response],
                metadatas=[{"role": "assistant", "timestamp": time.time()}],
                ids=[f"{int(time.time())}_{hash(response)}"]
            )
        except:
            pass
    
    return jsonify({"response": response})

@app.route('/api/verify_master', methods=['POST'])
def verify_master():
    data = request.json
    passkey = data.get('passkey', '')
    if passkey == MASTER_PASSKEY:
        return jsonify({"success": True, "master": True})
    return jsonify({"success": False, "master": False})

@app.route('/api/create_order', methods=['POST'])
def create_order():
    try:
        order = razorpay_client.order.create({
            'amount': 10000,
            'currency': 'INR',
            'payment_capture': '1'
        })
        return jsonify({"order_id": order['id']})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/verify_payment', methods=['POST'])
def verify_payment():
    data = request.json
    payment_id = data.get('payment_id')
    order_id = data.get('order_id')
    signature = data.get('signature')
    
    try:
        params_dict = {
            'razorpay_order_id': order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': signature
        }
        razorpay_client.utility.verify_payment_signature(params_dict)
        return jsonify({"success": True, "premium": True})
    except:
        return jsonify({"success": False}), 400

@app.route('/api/conversations', methods=['GET'])
def get_conversations():
    try:
        result = conv_collection.get(limit=100)
        convs = []
        if result and result['ids']:
            for idx, cid in enumerate(result['ids']):
                meta = result['metadatas'][idx]
                convs.append({
                    "id": cid,
                    "title": meta.get("title", "Untitled"),
                    "timestamp": meta.get("timestamp", 0),
                    "message_count": meta.get("message_count", 0)
                })
            convs.sort(key=lambda x: x["timestamp"], reverse=True)
        return jsonify(convs)
    except:
        return jsonify([])

@app.route('/api/load_conversation/<conv_id>', methods=['GET'])
def load_conversation(conv_id):
    try:
        result = conv_collection.get(ids=[conv_id])
        if result and result['documents']:
            return jsonify(json.loads(result['documents'][0]))
    except:
        pass
    return jsonify([])

@app.route('/api/save_conversation', methods=['POST'])
def save_conversation():
    data = request.json
    conv_id = data.get('id', str(int(time.time())))
    messages = data.get('messages', [])
    title = data.get('title', messages[0]['content'][:30] + '...' if messages else 'New Chat')
    
    if messages:
        conv_collection.upsert(
            ids=[conv_id],
            documents=[json.dumps(messages)],
            metadatas=[{
                "title": title,
                "timestamp": time.time(),
                "message_count": len(messages)
            }]
        )
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route('/api/delete_conversation/<conv_id>', methods=['DELETE'])
def delete_conversation(conv_id):
    try:
        conv_collection.delete(ids=[conv_id])
        return jsonify({"success": True})
    except:
        return jsonify({"success": False})

@app.route('/api/clear_memory', methods=['POST'])
def clear_memory():
    try:
        chroma_client.delete_collection("conversations")
        chroma_client.delete_collection("chat_memory")
        # Recreate
        conv_collection = chroma_client.create_collection("conversations", embedding_function=embedding_fn)
        memory_collection = chroma_client.create_collection("chat_memory", embedding_function=embedding_fn)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
