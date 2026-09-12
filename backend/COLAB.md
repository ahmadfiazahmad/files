# Google Colab quick start

```python
!pip install -r /content/VerifyAbroad-AI-backend/requirements.txt
```

Then run from the backend directory:

```python
%cd /content/VerifyAbroad-AI-backend
!python -m rag.knowledge_base
!uvicorn main:app --host 0.0.0.0 --port 8000
```

Upload/copy the package to Colab first. Configure `.env` before starting the server.

API docs: `http://127.0.0.1:8000/docs`
