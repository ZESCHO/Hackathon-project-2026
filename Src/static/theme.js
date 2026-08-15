// ============================================
// AI CHATBOT INTERFACE
// ============================================

const AI_RESPONSES = [
    "I can help you with institutional service requests. What would you like to do?",
    "I see you're interested in certificates. Would you like to request one?",
    "I can process maintenance requests quickly. What needs fixing?",
    "Laboratory bookings are my specialty! When do you need a lab?",
    "Grievances matter. Let me help you file one properly.",
    "Your request is important. I'll ensure it gets proper human oversight.",
    "Based on institutional policies, here's what I recommend:",
    "I've analyzed your request. Let me route this to the right department.",
    "Your approval status: This request requires human review. I've flagged it as priority.",
    "The AI-human workflow ensures your request gets the best outcome."
];

function openAIChat() {
    const modal = document.getElementById('ai-chat-modal');
    if (modal) {
        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
        setTimeout(() => {
            const input = document.getElementById('ai-input');
            if (input) input.focus();
        }, 100);
    }
}

function closeAIChat() {
    const modal = document.getElementById('ai-chat-modal');
    if (modal) {
        modal.style.display = 'none';
        document.body.style.overflow = 'auto';
    }
}

function sendAIMessage() {
    const input = document.getElementById('ai-input');
    const chatBox = document.getElementById('ai-chat-box');
    
    if (!input || !input.value.trim()) return;
    
    const userMessage = input.value;
    
    // Add user message
    const userDiv = document.createElement('div');
    userDiv.className = 'ai-message user-message';
    userDiv.innerHTML = `<div class="ai-message-content">${escapeHtml(userMessage)}</div>`;
    chatBox.appendChild(userDiv);
    
    input.value = '';
    
    // Simulate AI thinking
    const thinkingDiv = document.createElement('div');
    thinkingDiv.className = 'ai-message ai-thinking';
    thinkingDiv.innerHTML = '<div class="ai-message-content">🤖 Analyzing...</div>';
    chatBox.appendChild(thinkingDiv);
    
    // Auto-scroll
    chatBox.scrollTop = chatBox.scrollHeight;
    
    // Simulate AI response delay
    setTimeout(() => {
        thinkingDiv.remove();
        
        const aiResponse = AI_RESPONSES[Math.floor(Math.random() * AI_RESPONSES.length)];
        const aiDiv = document.createElement('div');
        aiDiv.className = 'ai-message bot-message';
        aiDiv.innerHTML = `<div class="ai-message-content">${escapeHtml(aiResponse)}</div>`;
        chatBox.appendChild(aiDiv);
        
        chatBox.scrollTop = chatBox.scrollHeight;
    }, 800);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Handle Enter key in chat input
document.addEventListener('DOMContentLoaded', function() {
    const aiInput = document.getElementById('ai-input');
    if (aiInput) {
        aiInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                sendAIMessage();
            }
        });
    }
    
    // Close modal on outside click
    const modal = document.getElementById('ai-chat-modal');
    if (modal) {
        modal.addEventListener('click', function(e) {
            if (e.target === modal) {
                closeAIChat();
            }
        });
    }
});
