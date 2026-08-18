// ============================================
// SHOW / HIDE PASSWORD
// ============================================
//
// Each password field is wrapped in .password-field with a button
// carrying data-target="<input id>". Revealing a password is a
// deliberate act, so it starts hidden and never persists: navigating
// away and back shows it masked again.

document.addEventListener('DOMContentLoaded', function () {

    const toggles = document.querySelectorAll('.password-toggle');

    toggles.forEach(function (toggle) {

        const field = document.getElementById(toggle.dataset.target);

        if (!field) return;

        toggle.addEventListener('click', function () {

            const revealed = field.type === 'text';

            field.type = revealed ? 'password' : 'text';

            toggle.textContent = revealed ? 'Show' : 'Hide';
            toggle.setAttribute(
                'aria-label',
                revealed ? 'Show password' : 'Hide password'
            );
            toggle.setAttribute('aria-pressed', String(!revealed));

            // Keep the caret where the user left it.
            field.focus();
        });
    });

    // Never leave a password on screen after the form is submitted.
    document.querySelectorAll('form').forEach(function (form) {
        form.addEventListener('submit', function () {
            toggles.forEach(function (toggle) {
                const field = document.getElementById(toggle.dataset.target);
                if (field) field.type = 'password';
            });
        });
    });
});
