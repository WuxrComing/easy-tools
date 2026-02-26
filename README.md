# Easy Tools - HTML + Python Backend Version

本分支提供 `HTML + FastAPI` 实现版本。

## 技术栈
- Frontend: HTML / CSS / Vanilla JS
- Backend: FastAPI + PyMuPDF + Pillow

## 功能
- 工具集合侧栏（可收缩，进入工具后自动收缩）
- PDF 预览（上一页/下一页/跳页）
- 预览模式：适应宽度 / 适应页面 / 百分比
- 页码范围导出：`9-11`、`1,3,9-11`
- 导出 PNG/JPG 并直接浏览器下载

## 安装
```bash
pip install -r requirements_web.txt
```

## 运行
```bash
uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

浏览器打开：
- http://127.0.0.1:8000

## 目录
- `backend/app.py` FastAPI 接口与 PDF 处理逻辑
- `web/index.html` 前端结构
- `web/styles.css` 前端样式
- `web/app.js` 前端交互逻辑
