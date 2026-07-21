from flask import Flask, request, jsonify, render_template_string
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
# CONFIG (Environment Variables)
# ─────────────────────────────────────────────────────────────

GROQ_API_KEY = os.environ.get("GROQ_API_KEY") or "your_groq_api_key_here"
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID") or "rzp_test_xxx"
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET") or "your_razorpay_secret"
MASTER_PASSKEY = os.environ.get("MASTER_PASSKEY") or "rengoku"

client = Groq(api_key=GROQ_API_KEY)
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# ─────────────────────────────────────────────────────────────
# CHROMADB (Persistent)
# ─────────────────────────────────────────────────────────────

CHROMA_PATH = "/tmp/universa_chroma_db"  # Render allows writing to /tmp
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
# LOGBOOK (JSON file in /tmp)
# ─────────────────────────────────────────────────────────────

LOGBOOK_FILE = "/tmp/universa_logbook.json"

def log_event(event_type, message):
    try:
        entry = {"timestamp": time.time(), "type": event_type, "message": message}
        with open(LOGBOOK_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except:
        pass

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
        log_event("error", f"Calculation error: {e}")
        return f"Error: {e}"

def search_wikipedia(query):
    try:
        import wikipedia
        summary = wikipedia.summary(query, sentences=3, auto_suggest=True)
        return f"Wikipedia: {summary}"
    except Exception as e:
        log_event("error", f"Wikipedia error: {e}")
        return "Wikipedia: No results found."

def get_model(premium=False, master=False):
    if premium or master:
        return "llama-3.3-70b-versatile"
    return "llama-3.1-8b-instant"

def get_max_tokens(premium=False, master=False):
    return 4096 if (premium or master) else 512

def get_context_limit(premium=False, master=False):
    return 120000 if (premium or master) else 4000

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
    
    trimmed = []
    total = count_tokens(system_prompt) + count_tokens(user_query) + 50
    for msg in reversed(history):
        msg_tokens = count_tokens(msg["content"])
        if total + msg_tokens > context_limit:
            log_event("trim", f"Context trimmed from {len(history)} to {len(trimmed)}")
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
        log_event("error", f"AI error: {e}")
        return f"Error: {e}"

# ─────────────────────────────────────────────────────────────
# FRONTEND (Embedded HTML/CSS/JS)
# ─────────────────────────────────────────────────────────────

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Universa AI</title>
    <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
    <style>
        /* ── Reset ── */
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: #0b0b14;
            color: #e8e8f0;
            height: 100vh;
            overflow: hidden;
        }
        .app {
            display: flex;
            height: 100vh;
            background: #0b0b14;
        }

        /* ── Sidebar ── */
        .sidebar {
            width: 280px;
            background: #12121e;
            padding: 20px 16px;
            display: flex;
            flex-direction: column;
            border-right: 1px solid #2a2a3e;
            overflow-y: auto;
            flex-shrink: 0;
        }
        .brand {
            font-size: 22px;
            font-weight: 700;
            color: #d0d0ff;
            margin-bottom: 18px;
            letter-spacing: -0.5px;
        }
        .brand span { color: #6a6aff; }
        .btn-new {
            background: #2a2a4e;
            color: #f0f0ff;
            border: none;
            padding: 10px 14px;
            border-radius: 10px;
            cursor: pointer;
            width: 100%;
            font-size: 14px;
            font-weight: 500;
            transition: background 0.2s;
            margin-bottom: 16px;
        }
        .btn-new:hover { background: #3a3a6e; }

        .chat-list {
            flex: 1;
            overflow-y: auto;
            margin-bottom: 16px;
        }
        .chat-item {
            padding: 8px 12px;
            margin: 4px 0;
            border-radius: 8px;
            cursor: pointer;
            font-size: 14px;
            transition: background 0.15s;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .chat-item:hover { background: #1e1e32; }
        .chat-item.active { background: #2a2a5a; }
        .chat-item .del {
            color: #8a6a6a;
            cursor: pointer;
            font-size: 12px;
            background: none;
            border: none;
        }
        .chat-item .del:hover { color: #ff6a6a; }

        .sidebar-footer {
            border-top: 1px solid #2a2a3e;
            padding-top: 12px;
        }
        .sidebar-footer button {
            background: #1e1e32;
            color: #d0d0e0;
            border: none;
            padding: 8px 12px;
            border-radius: 8px;
            cursor: pointer;
            width: 100%;
            font-size: 13px;
            transition: background 0.2s;
            margin-bottom: 6px;
        }
        .sidebar-footer button:hover { background: #2e2e4e; }

        /* ── Main ── */
        .main {
            flex: 1;
            display: flex;
            flex-direction: column;
            background: #0b0b14;
            min-width: 0;
        }
        .header {
            padding: 14px 24px;
            background: #12121e;
            border-bottom: 1px solid #2a2a3e;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-shrink: 0;
        }
        .header .engine {
            font-weight: 500;
            font-size: 15px;
            color: #b0b0d0;
        }
        .header .status {
            font-size: 13px;
            color: #6a8a6a;
        }

        .chat-area {
            flex: 1;
            overflow-y: auto;
            padding: 20px 24px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        .message {
            max-width: 80%;
            display: flex;
            flex-direction: column;
            animation: fadeIn 0.3s ease;
        }
        .message.user { align-self: flex-end; }
        .message.assistant { align-self: flex-start; }
        .message .sender {
            font-size: 12px;
            color: #6a6a8a;
            margin-bottom: 2px;
        }
        .message .content {
            padding: 10px 16px;
            border-radius: 14px;
            background: #1a1a2e;
            line-height: 1.5;
            word-wrap: break-word;
        }
        .message.user .content { background: #1a3a6a; color: #8ab4f8; }
        .message.assistant .content { background: #1a1a2e; color: #e8e8f0; }

        .input-area {
            display: flex;
            padding: 12px 24px 20px;
            background: #0b0b14;
            border-top: 1px solid #2a2a3e;
            flex-shrink: 0;
        }
        .input-area input {
            flex: 1;
            padding: 12px 16px;
            border: none;
            border-radius: 12px;
            background: #1a1a2e;
            color: #f0f0f0;
            font-size: 14px;
            outline: none;
            transition: background 0.2s;
        }
        .input-area input:focus { background: #22223e; }
        .input-area button {
            margin-left: 12px;
            padding: 12px 28px;
            background: #3a5a8a;
            border: none;
            border-radius: 12px;
            color: white;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s;
        }
        .input-area button:hover { background: #4a6a9a; }

        /* ── Logbook panel ── */
        .logbook-panel {
            background: #1a1a2e;
            border-radius: 10px;
            padding: 12px;
            margin-top: 8px;
            max-height: 200px;
            overflow-y: auto;
            display: none;
        }
        .logbook-panel.show { display: block; }
        .logbook-entry {
            font-size: 12px;
            padding: 3px 0;
            border-bottom: 1px solid #2a2a3e;
            color: #aaaabc;
        }

        /* ── Master panel ── */
        .master-panel {
            background: #1a1a2e;
            border-radius: 10px;
            padding: 12px;
            margin-top: 8px;
            display: none;
        }
        .master-panel.show { display: block; }
        .master-panel input {
            width: 100%;
            padding: 8px 12px;
            border: none;
            border-radius: 6px;
            background: #0b0b14;
            color: #f0f0f0;
        }
        .master-panel button {
            margin-top: 6px;
            width: 100%;
            padding: 8px;
            background: #3a5a8a;
            border: none;
            border-radius: 6px;
            color: white;
            cursor: pointer;
        }

        /* ── Animations ── */
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(6px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* ── Scrollbar ── */
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #0b0b14; }
        ::-webkit-scrollbar-thumb { background: #2a2a4e; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #3a3a6e; }

        /* ── Responsive ── */
        @media (max-width: 700px) {
            .sidebar { width: 220px; padding: 14px; }
            .main .header { padding: 10px 16px; }
            .chat-area { padding: 12px 16px; }
            .input-area { padding: 10px 16px 16px; }
        }
        @media (max-width: 500px) {
            .app { flex-direction: column; }
            .sidebar { width: 100%; height: auto; max-height: 40vh; border-right: none; border-bottom: 1px solid #2a2a3e; }
            .main { height: 60vh; }
        }
    </style>
</head>
<body>
<div class="app">
    <!-- Sidebar -->
    <aside class="sidebar">
        <div class="brand">🛰️ <span>Universa</span></div>
        <button class="btn-new" onclick="newChat()">✏️ New Chat</button>
        <div class="chat-list" id="chatList"></div>
        <div class="sidebar-footer">
            <button onclick="toggleLogbook()">📜 Logbook</button>
            <div class="logbook-panel" id="logbookPanel">
                <div id="logbookEntries"></div>
                <button style="margin-top:6px; background:#3a2a2a;" onclick="clearLogbook()">Clear Logs</button>
            </div>
            <button onclick="toggleMaster()">🔑 Master</button>
            <div class="master-panel" id="masterPanel">
                <input type="password" id="passkeyInput" placeholder="Enter passkey...">
                <button onclick="verifyPasskey()">Unlock</button>
            </div>
            <button onclick="clearMemory()" style="background:#2a1a2a;">🧹 Clear Memory</button>
        </div>
    </aside>

    <!-- Main chat -->
    <main class="main">
        <div class="header">
            <span class="engine" id="engineDisplay">Universa Standard</span>
            <span class="status" id="statusDisplay">🟢 Connected</span>
        </div>
        <div class="chat-area" id="chatArea"></div>
        <div class="input-area">
            <input type="text" id="userInput" placeholder="Ask Universa anything..." onkeydown="if(event.key==='Enter') sendMessage()">
            <button onclick="sendMessage()">Send</button>
        </div>
    </main>
</div>

<script>
    // ── State ──
    let chatHistory = [];
    let conversationId = null;
    let isPremium = false;
    let isMaster = false;
    let currentConversationId = null;

    // ── DOM refs ──
    const chatArea = document.getElementById('chatArea');
    const userInput = document.getElementById('userInput');
    const chatList = document.getElementById('chatList');
    const engineDisplay = document.getElementById('engineDisplay');
    const statusDisplay = document.getElementById('statusDisplay');

    // ── Load conversations on load ──
    loadConversations();

    // ── Send message ──
    function sendMessage() {
        const msg = userInput.value.trim();
        if (!msg) return;
        userInput.value = '';

        addMessage('user', msg);
        chatHistory.push({ role: 'user', content: msg });

        fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: msg,
                history: chatHistory,
                premium: isPremium,
                master: isMaster
            })
        })
        .then(r => r.json())
        .then(data => {
            addMessage('assistant', data.response);
            chatHistory.push({ role: 'assistant', content: data.response });
            saveCurrentConversation();
        })
        .catch(err => {
            addMessage('assistant', '❌ Error: ' + err.message);
        });
    }

    function addMessage(role, content) {
        const div = document.createElement('div');
        div.className = `message ${role}`;
        div.innerHTML = `<div class="sender">${role === 'user' ? 'You' : 'Universa'}</div>
                         <div class="content">${content.replace(/</g,'&lt;').replace(/>/g,'&gt;')}</div>`;
        chatArea.appendChild(div);
        chatArea.scrollTop = chatArea.scrollHeight;
    }

    // ── New Chat ──
    function newChat() {
        if (chatHistory.length > 0) saveCurrentConversation();
        chatHistory = [];
        conversationId = Date.now().toString();
        chatArea.innerHTML = '';
        engineDisplay.textContent = isMaster ? '👑 Universa Master' : isPremium ? '⚡ Universa Premium' : 'Universa Standard';
        loadConversations();
    }

    // ── Save conversation ──
    function saveCurrentConversation() {
        if (!chatHistory.length) return;
        const title = chatHistory[0].content.slice(0, 30) + '...';
        fetch('/api/save_conversation', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                id: conversationId || Date.now().toString(),
                messages: chatHistory,
                title: title
            })
        });
    }

    // ── Load conversations list ──
    function loadConversations() {
        fetch('/api/conversations')
            .then(r => r.json())
            .then(convs => {
                chatList.innerHTML = '';
                const groups = groupConversations(convs);
                for (const [label, items] of Object.entries(groups)) {
                    if (items.length) {
                        const labelEl = document.createElement('div');
                        labelEl.style.cssText = 'font-size:12px;color:#6a6a8a;padding:8px 0 4px;';
                        labelEl.textContent = label;
                        chatList.appendChild(labelEl);
                        items.forEach(c => {
                            const div = document.createElement('div');
                            div.className = 'chat-item';
                            div.innerHTML = `<span>${c.title}</span><button class="del" onclick="event.stopPropagation(); deleteConv('${c.id}')">✕</button>`;
                            div.onclick = () => loadConversation(c.id);
                            chatList.appendChild(div);
                        });
                    }
                }
            });
    }

    function groupConversations(convs) {
        const now = Date.now() / 1000;
        const today = now - 86400;
        const week = now - 604800;
        const month = now - 2592000;
        const groups = { Today: [], '7 Days': [], '30 Days': [], Older: [] };
        convs.forEach(c => {
            if (c.timestamp >= today) groups.Today.push(c);
            else if (c.timestamp >= week) groups['7 Days'].push(c);
            else if (c.timestamp >= month) groups['30 Days'].push(c);
            else groups.Older.push(c);
        });
        return groups;
    }

    function loadConversation(id) {
        fetch(`/api/load_conversation/${id}`)
            .then(r => r.json())
            .then(messages => {
                if (messages.length) {
                    chatHistory = messages;
                    conversationId = id;
                    chatArea.innerHTML = '';
                    messages.forEach(m => addMessage(m.role, m.content));
                    engineDisplay.textContent = isMaster ? '👑 Universa Master' : isPremium ? '⚡ Universa Premium' : 'Universa Standard';
                }
            });
    }

    function deleteConv(id) {
        if (!confirm('Delete this conversation?')) return;
        fetch(`/api/delete_conversation/${id}`, { method: 'DELETE' })
            .then(() => loadConversations());
    }

    // ── Master Passkey ──
    function toggleMaster() {
        const panel = document.getElementById('masterPanel');
        panel.classList.toggle('show');
    }

    function verifyPasskey() {
        const passkey = document.getElementById('passkeyInput').value;
        fetch('/api/verify_master', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ passkey })
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                isMaster = true;
                engineDisplay.textContent = '👑 Universa Master';
                document.getElementById('masterPanel').classList.remove('show');
                alert('Master unlocked!');
            } else {
                alert('❌ Invalid passkey');
            }
        });
    }

    // ── Logbook ──
    function toggleLogbook() {
        const panel = document.getElementById('logbookPanel');
        panel.classList.toggle('show');
        if (panel.classList.contains('show')) loadLogbook();
    }

    function loadLogbook() {
        fetch('/api/logbook')
            .then(r => r.json())
            .then(logs => {
                const entries = document.getElementById('logbookEntries');
                entries.innerHTML = logs.map(l => `<div class="logbook-entry">[${new Date(l.timestamp*1000).toLocaleTimeString()}] ${l.type}: ${l.message}</div>`).join('');
            });
    }

    function clearLogbook() {
        if (!confirm('Clear all logs?')) return;
        fetch('/api/clear_logbook', { method: 'POST' })
            .then(() => { document.getElementById('logbookEntries').innerHTML = ''; });
    }

    // ── Clear Memory ──
    function clearMemory() {
        if (!confirm('Clear all memory? This cannot be undone.')) return;
        fetch('/api/clear_memory', { method: 'POST' })
            .then(() => {
                chatHistory = [];
                chatArea.innerHTML = '';
                loadConversations();
            });
    }
</script>
</body>
</html>
"""

# ─────────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/ping')
def ping():
    return "pong"

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json
    user_input = data.get('message', '')
    history = data.get('history', [])
    premium = data.get('premium', False)
    master = data.get('master', False)
    
    response = generate_response(user_input, history, premium, master)
    
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
        log_event("master", "Master unlocked via passkey")
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
        log_event("order", f"Order created: {order['id']}")
        return jsonify({"order_id": order['id']})
    except Exception as e:
        log_event("error", f"Order creation failed: {e}")
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
        log_event("premium", "Premium unlocked via payment")
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
            log_event("load", f"Loaded conversation {conv_id}")
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
        log_event("delete", f"Deleted conversation {conv_id}")
        return jsonify({"success": True})
    except:
        return jsonify({"success": False})

@app.route('/api/clear_memory', methods=['POST'])
def clear_memory():
    try:
        chroma_client.delete_collection("conversations")
        chroma_client.delete_collection("chat_memory")
        # Recreate
        global conv_collection, memory_collection
        conv_collection = chroma_client.create_collection("conversations", embedding_function=embedding_fn)
        memory_collection = chroma_client.create_collection("chat_memory", embedding_function=embedding_fn)
        log_event("clear", "All memory cleared")
        return jsonify({"success": True})
    except Exception as e:
        log_event("error", f"Clear memory error: {e}")
        return jsonify({"success": False, "error": str(e)})

@app.route('/api/logbook', methods=['GET'])
def get_logbook():
    try:
        if not os.path.exists(LOGBOOK_FILE):
            return jsonify([])
        with open(LOGBOOK_FILE, 'r') as f:
            lines = f.readlines()
            logs = [json.loads(line) for line in lines if line.strip()]
            logs.sort(key=lambda x: x['timestamp'], reverse=True)
            return jsonify(logs[:100])
    except:
        return jsonify([])

@app.route('/api/clear_logbook', methods=['POST'])
def clear_logbook():
    try:
        if os.path.exists(LOGBOOK_FILE):
            os.remove(LOGBOOK_FILE)
        return jsonify({"success": True})
    except:
        return jsonify({"success": False})

# ─────────────────────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
