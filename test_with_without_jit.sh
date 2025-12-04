#!/bin/bash

echo "=========================================="
echo "测试1: 禁用JIT（纯Python）"
echo "=========================================="
export NUMBA_DISABLE_JIT=1
time .venv/bin/python BBA_dev/scripts/run_batch_process_new.py 20 2>&1 | grep -E "DONE|Total"

echo ""
echo "=========================================="
echo "测试2: 启用JIT（机器码）"  
echo "=========================================="
unset NUMBA_DISABLE_JIT
time .venv/bin/python BBA_dev/scripts/run_batch_process_new.py 20 2>&1 | grep -E "DONE|Total"
