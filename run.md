# How to Run AutoSDLC

This document provides step-by-step instructions to run the AutoSDLC project locally or via Docker.

---

## Prerequisites

- **Python**: 3.10 or higher
- **Node.js**: 18.x or higher (with npm)
- **Git** (optional, for version control)
- **Docker & Docker Compose** (optional, for containerized execution)

---

## 1. Quick Start (Local Development)

To run the complete app locally, you need two terminal tabs: one for the **Python Backend** and one for the **React Frontend**.

### Terminal 1: Backend (FastAPI)

```bash
# 1. Navigate to the project root
cd /path/to/story-generator

# 2. Create and activate a Python virtual environment (if not already done)
python3 -m venv venv
source venv/bin/activate

# 3. Install backend dependencies
pip install -r requirements.txt

# 4. Configure environment variables
# Copy .env.example to .env and add your AI provider API keys (Groq, OpenAI, Anthropic, Mistral, Gemini, etc.)
cp .env.example .env

# 5. Start the backend server
uvicorn main:app --reload --port 8000
```
> The backend API will be running at `http://localhost:8000` (API documentation at `http://localhost:8000/docs`).

---

### Terminal 2: Frontend (Vite + React)

```bash
# 1. Navigate to the frontend directory
cd frontend

# 2. Install dependencies
npm install

# 3. Start the Vite development server
npm run dev
```
> The frontend UI will be running at `http://localhost:5173`. Requests are automatically proxied to the backend on port 8000.

---

## 2. Production Build (Single Server Mode)

In production, FastAPI can serve the built frontend static files directly from a single port without needing Vite running:

```bash
# 1. Build frontend static assets into the /static folder
cd frontend
npm run build
cd ..

# 2. Start the FastAPI server
uvicorn main:app --host 0.0.0.0 --port 8000
```
> Open `http://localhost:8000` in your browser to access the complete application.

---

## 3. Running with Docker Compose

If you prefer running with Docker:

```bash
# 1. Ensure .env is populated with your API keys
cp .env.example .env

# 2. Build and start the container
docker compose up --build -d
```
> Access the application at `http://localhost:8000`.

To stop the container:
```bash
docker compose down
```

---

## 4. Running Tests

### Backend Tests (Python / Pytest)
```bash
# Run all 300+ pytest tests
pytest

# Run tests with output logs
pytest -v
```

### Frontend Checks (TypeScript / Lint / Design Tokens)
```bash
cd frontend
npm run build
```

---

## 5. Configuration & Environment Variables

Key variables in `.env`:
- `GROQ_API_KEY`: API key for Groq (Llama models)
- `OPENAI_API_KEY`: API key for OpenAI (GPT models)
- `ANTHROPIC_API_KEY`: API key for Anthropic (Claude models)
- `MISTRAL_API_KEY`: API key for Mistral
- `GEMINI_API_KEY`: API key for Google Gemini
- `REDMINE_URL`: Optional default Redmine server URL
- `REDMINE_API_KEY`: Optional default Redmine API key
- `BITBUCKET_WORKSPACE`: Optional default Bitbucket workspace
- `BITBUCKET_API_TOKEN`: Optional default Bitbucket API token
