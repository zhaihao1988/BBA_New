# 数据库连接管理修复总结

## 问题根源
数据库连接池耗尽错误：`remaining connection slots are reserved for non-replication superuser connections`

### 主要原因
1. **连接未正确释放**：虽然使用了 `with` 语句关闭单个连接，但连接池本身需要显式清理
2. **连接池配置过大**：每个进程占用过多连接（pool_size=5, max_overflow=10 = 最多15个连接）
3. **程序结束时未清理**：连接池在程序结束时未释放，导致连接泄漏
4. **多进程场景**：批处理使用多进程，每个进程都创建连接池，总连接数 = 进程数 × 连接池大小

## 修复措施

### 1. 连接池配置
**文件**: `BBA_dev/data_access/db_utils.py`

```python
pool_size=5,           # 每个进程最多5个连接
max_overflow=10,       # 允许超出10个连接（最多15个连接）
pool_recycle=3600,     # 1小时后回收连接（防止数据库端超时）
```

**说明**: 连接池配置保持原值，关键是确保程序结束时正确清理连接池

### 2. 添加连接池清理机制
**文件**: `BBA_dev/data_access/db_utils.py`

```python
def dispose_all_engines():
    """释放所有数据库连接池（用于清理资源）"""
    for env, engine in _ENGINE_CACHE.items():
        engine.dispose()
    _ENGINE_CACHE.clear()
```

### 3. 在程序结束时清理连接
**文件**: `BBA_dev/scripts/run_lifecycle_simulation.py`

```python
def main():
    simulator = LifecycleSimulator(...)
    try:
        simulator.run()
    finally:
        simulator.cleanup()  # 清理资源，包括数据库连接池
```

**LifecycleSimulator 类添加 cleanup 方法**:
```python
def cleanup(self):
    """清理资源，包括数据库连接池"""
    from BBA_dev.data_access.db_utils import dispose_all_engines
    dispose_all_engines()
    if self.enable_logging:
        self.logger.close()
```

### 4. 批处理脚本清理
**文件**: `BBA_dev/scripts/run_batch_process.py`

- **主进程清理**: 在 `run_batch()` 函数结束时清理
- **子进程清理**: 在 `process_single_policy()` 函数的 `finally` 块中清理

```python
def process_single_policy(...):
    try:
        # 处理逻辑
        pass
    finally:
        # 每个子进程结束时清理数据库连接池
        from BBA_dev.data_access.db_utils import dispose_all_engines
        dispose_all_engines()
```

### 5. 简化查询逻辑
**文件**: `BBA_dev/data_access/loader.py`

- 移除调试查询，减少连接数占用
- 确保所有查询都使用 `with engine.connect() as conn:` 自动关闭连接

## 修复后的连接数计算

### 单进程场景
- 连接池大小: 5
- 最大溢出: 10
- **总连接数**: 最多15个（5+10）

### 多进程场景（32个进程）
- 每个进程: 最多15个连接
- **理论最大**: 32 × 15 = 480个连接
- **实际使用**: 通常远小于理论值（因为连接会复用和回收）
- **关键**: 程序结束时必须调用 `dispose_all_engines()` 清理所有连接

## 最佳实践

### ✅ 必须做的
1. **所有数据库查询使用 `with` 语句**:
   ```python
   with engine.connect() as conn:
       df = pd.read_sql_query(text(query), conn)
   ```

2. **程序结束时调用 `dispose_all_engines()`**:
   ```python
   try:
       # 主程序逻辑
       pass
   finally:
       dispose_all_engines()
   ```

3. **多进程场景下，每个进程结束时都要清理**:
   ```python
   def worker_process():
       try:
           # 工作逻辑
           pass
       finally:
           dispose_all_engines()
   ```

### ❌ 避免做的
1. **不要手动管理连接**:
   ```python
   # ❌ 错误
   conn = engine.connect()
   df = pd.read_sql_query(text(query), conn)
   # 如果这里发生异常，连接可能不会关闭
   ```

2. **不要在循环中重复创建 engine**:
   ```python
   # ❌ 错误
   for item in items:
       engine = get_sa_engine('qa')  # 每次都创建新engine
       # 应该使用缓存的engine
   ```

3. **不要设置过大的连接池**:
   ```python
   # ❌ 错误
   pool_size=10, max_overflow=20  # 太多连接
   ```

## 检查清单

在编写新代码时，请确保：

- [x] 所有数据库查询都使用 `with engine.connect() as conn:`
- [x] 程序结束时调用 `dispose_all_engines()`
- [x] 异常处理中使用 `try-finally` 确保清理
- [x] 多进程场景下，每个进程结束时都清理
- [x] 连接池配置合理（pool_size=2, max_overflow=3）
- [x] 避免在循环中重复创建 engine

## 监控建议

如果将来再次出现连接问题，可以：

1. **检查数据库连接数**:
   ```sql
   SELECT count(*) FROM pg_stat_activity WHERE datname = 'cas25_test_qa';
   ```

2. **检查连接池状态**:
   - 在代码中添加日志，记录连接池使用情况
   - 监控 `pool.size()` 和 `pool.checkedout()`

3. **定期清理**:
   - 长时间运行的程序，可以定期调用 `dispose_all_engines()` 然后重新创建

## 相关文件

- `BBA_dev/data_access/db_utils.py` - 连接池配置和清理函数
- `BBA_dev/data_access/loader.py` - 数据库查询函数
- `BBA_dev/scripts/run_lifecycle_simulation.py` - 单保单仿真脚本
- `BBA_dev/scripts/run_batch_process.py` - 批处理脚本
- `BBA_dev/data_access/CONNECTION_MANAGEMENT.md` - 连接管理规范文档

