# NeuroAxis Web (前端)

Vue 3 + Vite 工作台，前后端分离：后端为 FastAPI (`plcagent.api.app`)，前端仅通过 `/api/v1` HTTP 调用。

## 开发

```bash
cd web
npm install
npm run dev          # http://localhost:5173，/api 代理到 :8000
```

后端另开终端：

```bash
uvicorn plcagent.api.app:app --reload --port 8000
```

可选鉴权：后端设 `PLCAGENT_API_KEY`，前端 `.env.local` 设 `VITE_API_KEY`。
