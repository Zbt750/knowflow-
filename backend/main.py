from backend.app import create_app

# Uvicorn 固定从这里找到 app；导入时不执行迁移或模型下载。
app = create_app()