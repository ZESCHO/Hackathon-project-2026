# Team Git & GitHub Guide

Press Ctrl + Shift + V if viewing from VS code

Welcome to the team! We have **two repositories** set up:
1. **`hackathon-prep`**: For notes, study materials, and cheat sheets.
2. **`hackathon-test-project`**: For our practice codebase.

---

## 1. How We Use Each Repo

### A. Prep Repo (`hackathon-prep`)
* **Rule:** Only work inside your own folder (`members/your-name/`).
* Direct pushes to `main` are allowed here.

### B. Code Repo (`hackathon-test-project`)
* **Rule:** **NEVER push directly to `main`**.
* Always create a new branch for your task, push it, and open a **Pull Request (PR)** on GitHub so someone can approve it.

---

## 🛠️ 2. Step-by-Step Command Manual

### Step 1: Initial Setup (Do once per repo)
Clone the repo to your computer:
```bash
git clone <REPO_URL>
cd <REPO_NAME>
```

---

### Step 2A: Adding Notes (`hackathon-prep`)
1. Add your notes inside your folder (`members/your-name/`).
2. Save changes, then run:
```bash
git add .
git commit -m "Add notes on React hooks"
git push origin main
```

---

### Step 2B: Writing Code (`hackathon-test-project`)

#### 1. Get the latest code first:
```bash
git checkout main
git pull origin main
```

#### 2. Create and switch to a feature branch:
```bash
# Naming convention: feature/your-task-name
git checkout -b feature/login-screen
```

#### 3. Save, commit, and push your work:
```bash
git add .
git commit -m "Add login form UI"
git push origin feature/login-screen
```

#### 4. Open a Pull Request (PR):
1. Go to GitHub in your browser.
2. Click **Compare & pull request**.
3. Ask a teammate to review and merge it into `main`.

---

## ⚠️ 3. Golden Rules to Prevent Issues

1. **Pull Before You Code:** Always run `git pull origin main` before starting a new feature to avoid code conflicts.
2. **Commit Often:** Small commits (e.g., `git commit -m "Fix button color"`) are easier to fix than one huge commit at the end of the day.
3. **Descriptive Messages:** Write clear commit messages so others know what changed.
4. **When in Doubt, Ask:** If Git shows a red error message or mentions a "merge conflict," stop and ask the group!

