async function askAI() {

    const message = document
        .getElementById("aiMessage")
        .value
        .trim();

    const resultBox = document.getElementById("aiResult");

    if (!message) {
        resultBox.innerHTML =
            "<p>Please enter your request.</p>";
        return;
    }

    resultBox.innerHTML =
        "<p>🤖 AI is understanding your request...</p>";

    try {

        const response = await fetch(
            "/api/agent/understand",
            {
                method: "POST",

                headers: {
                    "Content-Type": "application/json"
                },

                body: JSON.stringify({
                    message: message
                })
            }
        );

        const data = await response.json();

        if (data.success) {

            resultBox.innerHTML = `
                <div class="ai-response">
                    <h3>🤖 AI Analysis</h3>
                    <p>${data.response}</p>

                    <div class="approval-warning">
                        ⚠️ Consequential actions require human approval.
                    </div>
                </div>
            `;

        } else {

            resultBox.innerHTML = `
                <p class="error">
                    ❌ ${data.error}
                </p>
            `;
        }

    } catch (error) {

        resultBox.innerHTML = `
            <p class="error">
                ❌ Unable to connect to the AI service.
            </p>
        `;
    }
}