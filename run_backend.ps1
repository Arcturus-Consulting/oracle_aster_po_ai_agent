param(
  [int]$Port = 8000
)

$env:APP_PORT = "$Port"
python -m uvicorn backend.main:app --host 127.0.0.1 --port $Port --reload
