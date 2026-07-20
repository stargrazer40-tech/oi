let chatHistory = [];
let conversationId = null;
let isPremium = false;
let isMaster = false;
let currentConversationId = null;

// ── DOM refs ──
const chatArea = document.getElementById('chatArea');
const userInput = document.getElementById('userInput');
const chatList = document.getElementById('chatList');

// ── Load conversations on page load ──
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
                     <div class="content">${content}</div>`;
    chatArea.appendChild(div);
    chatArea.scrollTop = chatArea.scrollHeight;
}

// ── New Chat ──
function newChat() {
    if (chatHistory.length > 0) saveCurrentConversation();
    chatHistory = [];
    conversationId = Date.now().toString();
    chatArea.innerHTML = '';
    document.getElementById('engineDisplay').textContent = 'Universa Standard Engine';
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
                        div.textContent = c.title;
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
                document.getElementById('engineDisplay').textContent = isMaster ? '👑 Universa Master' : isPremium ? '⚡ Universa Premium' : 'Universa Standard Engine';
            }
        });
}

// ── Master Passkey ──
function toggleMaster() {
    const container = document.getElementById('masterContainer');
    container.style.display = container.style.display === 'none' ? 'block' : 'none';
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
            document.getElementById('engineDisplay').textContent = '👑 Universa Master';
            document.getElementById('masterContainer').style.display = 'none';
        } else {
            alert('❌ Invalid passkey');
        }
    });
}

// ── Logbook ──
function toggleLogbook() {
    const container = document.getElementById('logbookContainer');
    container.style.display = container.style.display === 'none' ? 'block' : 'none';
    if (container.style.display === 'block') loadLogbook();
}

function loadLogbook() {
    fetch('/api/logbook')
        .then(r => r.json())
        .then(logs => {
            const entries = document.getElementById('logbookEntries');
            entries.innerHTML = logs.map(l => `<div>[${new Date(l.timestamp*1000).toLocaleTimeString()}] ${l.type}: ${l.message}</div>`).join('');
        });
}

function clearLogbook() {
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
