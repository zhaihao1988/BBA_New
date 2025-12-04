# 数据库连接管理规范

## 问题总结
数据库连接池耗尽问题通常由以下原因引起：
1. **连接未正确关闭**：虽然使用了 `with` 语句，但连接池本身需要显式清理
2. **连接池配置过大**：每个进程占用过多连接
3. **异常情况下连接泄漏**：异常时连接未正确释放
4. **程序结束时未清理**：连接池在程序结束时未释放

## 连接管理规范

### 1. 使用 `with` 语句确保连接自动关闭
```python
# ✅ 正确：使用 with 语句
with engine.connect() as conn:
    df = pd.read_sql_query(text(query), conn)

# ❌ 错误：手动管理连接
conn = engine.connect()
df = pd.read_sql_query(text(query), conn)
# 如果这里发生异常，连接可能不会关闭
```

### 2. 连接池配置
- `pool_size=2`：每个进程最多2个连接
- `max_overflow=3`：最多允许5个连接（2+3）
- `pool_recycle=1800`：30分钟后回收连接
- `pool_pre_ping=True`：连接前检查有效性

### 3. 程序结束时必须清理连接池
```python
from BBA_dev.data_access.db_utils import dispose_all_engines

try:
    # 主程序逻辑
    pass
finally:
    dispose_all_engines()  # 必须调用
```

### 4. 异常处理
所有数据库操作都应该有异常处理，确保连接正确释放：
```python
try:
    with engine.connect() as conn:
        # 数据库操作
        pass
except Exception as e:
    # 异常处理
    # with 语句会自动关闭连接
    pass
```

## 检查清单

- [x] 所有数据库查询都使用 `with engine.connect() as conn:`
- [x] 连接池配置合理（pool_size=2, max_overflow=3）
- [x] 程序结束时调用 `dispose_all_engines()`
- [x] 异常处理确保连接释放
- [x] 避免在循环中重复创建 engine（使用缓存的 engine）

## 常见问题

### Q: 为什么使用 `with` 语句后还需要 `dispose_all_engines()`？
A: `with` 语句只关闭单个连接，但连接池本身需要显式清理。`dispose_all_engines()` 会关闭连接池中的所有连接并释放资源。

### Q: 什么时候需要调用 `dispose_all_engines()`？
A: 
- 程序正常结束时
- 程序异常退出时（使用 try-finally）
- 批处理程序处理完一批数据后
- 长时间运行的程序定期清理时

### Q: 连接池配置如何选择？
A: 
- 单进程程序：pool_size=2, max_overflow=3（最多5个连接）
- 多进程程序：每个进程 pool_size=1, max_overflow=2（最多3个连接）
- 高并发程序：需要根据实际负载调整

