@echo off
REM Rebuild vector index for all materials (run from project root)
REM The vector store is a rebuildable derived index; PostgreSQL keeps the text.
cd /d "%~dp0.."
python scripts\rebuild_all_indexes.py
pause