// ============================================
// AI CHAT MODAL - UI WIRING ONLY
// ============================================
//
// This file deliberately contains no canned answers. Every reply the
// user sees must come from the /chat endpoint, which answers only from
// verified institutional sources. A hardcoded response here would be
// the platform fabricating an answer.

function openAIChat() {
    const modal = document.getElementById('ai-chat-modal');
    if (!modal) return;

    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';

    setTimeout(() => {
        const input = document.getElementById('ai-input');
        if (input) input.focus();
    }, 100);
}

function closeAIChat() {
    const modal = document.getElementById('ai-chat-modal');
    if (!modal) return;

    modal.style.display = 'none';
    document.body.style.overflow = 'auto';
}

document.addEventListener('DOMContentLoaded', function () {

    const aiInput = document.getElementById('ai-input');

    if (aiInput) {
        aiInput.addEventListener('keypress', function (event) {
            // sendAIMessage is defined by the page hosting the chat.
            if (event.key === 'Enter' && typeof sendAIMessage === 'function') {
                sendAIMessage();
            }
        });
    }

    const modal = document.getElementById('ai-chat-modal');

    if (modal) {
        modal.addEventListener('click', function (event) {
            if (event.target === modal) {
                closeAIChat();
            }
        });
    }
});
