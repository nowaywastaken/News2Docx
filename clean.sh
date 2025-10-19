#!/bin/bash
# 清理项目中的临时文件和缓存

echo "清理 Python 缓存..."
find . -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete 2>/dev/null
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null

echo "清理 .n2d_cache JSON 文件..."
rm -f .n2d_cache/*.json 2>/dev/null

echo "清理 Ruff 缓存..."
rm -rf .ruff_cache 2>/dev/null

echo "清理 pytest 缓存..."
rm -rf .pytest_cache 2>/dev/null

echo "清理构建产物..."
rm -rf build dist *.spec 2>/dev/null

echo "清理完成！"
