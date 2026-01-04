# BBA Lifecycle Simulation Java 开发文档

## 1. 项目概述

本项目是 IFRS 17 BBA (Building Block Approach) 全生命周期模拟计算引擎的 Java 版本实现。
原项目为 Python 实现，本项目基于 **Spring Boot 3.2.1** + **MyBatis-Plus 3.5.5** 框架进行了重构，旨在提供更强的类型安全、更高的性能和更好的企业级集成能力。

## 2. 技术栈

- **核心框架**: Spring Boot 3.2.1
- **ORM 框架**: MyBatis-Plus 3.5.5
- **数据库**: PostgreSQL (兼容现有 Python 版数据库配置)
- **构建工具**: Maven
- **工具库**: Lombok, FastJSON, Apache Commons
- **JDK 版本**: JDK 17+

## 3. 核心架构与模块映射

本项目严格遵循 Python 原版的计算逻辑，将各个 Python 模块映射为 Java Service 组件。

| Python 模块 | Java Service | 描述 |
| :--- | :--- | :--- |
| `run_lifecycle_simulation.py` | `LifecycleSimulationService` | 模拟计算的主入口，协调各个计算步骤，**串联全流程** |
| `fulfillment_cashflow_changes.py` | `FulfillmentCashflowChangesService` | 计算履约现金流的变化（经验调整、假设变更等） |
| `csm_lc_measurement.py` | `CsmLcMeasurementService` | CSM（合同服务边际）和 LC（亏损构件）的计量与分摊 |
| `coverage_units.py` | `CoverageUnitsService` | 覆盖单元（Coverage Units）的计算与释放比例 |
| `pv_calculator.py` | `PVGeneratorService` | **[新增]** PV 核心计算引擎，负责内存中生成 PV 数据 |
| `rates_manager.py` | `RatesManagerService` | 利率曲线管理与插值计算 |

### 3.1 数据模型 (Data Models)

- **CalculationContext**: 计算上下文对象，存储单次模拟全过程中的中间变量（如 `bopCsm`, `deltaPrem`, `endLcFinal` 等）。
- **PVSourceData**: **[核心改进]** PV 原材料数据的强类型实体类。取代了 Python 中动态的 JSON 字典，提供了所有 PV 字段（如 `Pvfl_Nb_Eop_Cfa_Rep_Wlk_Pre_Amt`）的明确定义和 Getter 方法，极大提高了代码的可读性和类型安全性。
- **CohortState**: 合同组状态对象，用于在不同评估年份之间传递状态（如 CSM 余额、LC 余额、亏损状态等）。
- **PolicyState**: 保单维度的状态对象。

## 4. 核心逻辑详解

### 4.1 PV 数据处理 (PV Data Handling) - **[重大更新]**

**最新改进**：完全移除了对 Python 生成的 JSON 文件的依赖，实现了全链路 Java 内存计算。

1.  **内存生成 (In-Memory Generation)**:
    - 新增 `PVGeneratorService` 和 `PVCalculatorService`，完整复刻了 Python `pv_calculator.py` 的核心逻辑。
    - 实现了包括 `calculatePvExact`, `calculatePvInitialRecognition`, `calculatePvBegLcu` (BOP 特殊逻辑) 在内的所有精算现值计算公式。
    - 数据不再写入磁盘 JSON 文件，而是直接生成 `PVSourceData` 对象供后续流程使用。

2.  **数据流转**:
    - `DataLoaderService`: 从数据库加载保单、假设、利率曲线。
    - `CashFlowProjectorService`: 基于保单和假设预测月度现金流 (Premium, IACF, Claims, Expenses)。
    - `PVCalculatorService`: 对预测的现金流进行精算折现（支持 Locked/Current 曲线，支持 BOP/EOP/Initial Recognition 等不同时点逻辑）。
    - `PVSourceLoaderService`: 编排上述服务，动态生成 `PVSourceDataCollection`，无缝替代旧版的 JSON 加载模式。

3.  **强类型实体**: `PVSourceData` 实体类保持不变，但其数据来源现在是 Java 原生计算结果，而非 JSON 解析结果。

### 4.2 履约现金流变化 (Fulfillment Cashflow Changes)

`FulfillmentCashflowChangesService` 负责计算各类现金流的变化，包括：
- **经验调整 (Experience Adjustment)**: 比较预期现金流与实际现金流的差异。
- **假设变更 (Assumption Changes)**: 比较不同利率/假设下的现值差异。
- **逻辑**: 严格复刻 `fulfillment_cashflow_changes.py` 中的公式，使用 `BigDecimal` 保证精度。

### 4.3 CSM 与 LC 计量 (CSM & LC Measurement)

`CsmLcMeasurementService` 是计算的核心，包含：
1.  **CSM 计息**: 计算期初 CSM 的利息累积。
2.  **LC 分摊 IFIE**: 将投资成分（IFIE）分摊到亏损构件（LC）上。
3.  **合同组状态判定**: 根据净余额试算值判定合同组是盈利还是亏损。
4.  **LC 计量**: 计算期末 LC 余额。
5.  **CSM 计量**: 计算期末 CSM 余额，处理 CSM 摊销和吸收变化。

## 5. 数据库配置

配置文件位于 `src/main/resources/application-dev.yml`。
项目配置了多数据源或动态 Schema 支持，以访问 `zh` (保单数据) 和 `curve` (利率数据) 等 Schema。

```yaml
spring:
  datasource:
    url: jdbc:postgresql://localhost:5432/postgres?currentSchema=zh
    username: postgres
    password: password
```

## 6. 如何运行

1.  **环境准备**: 确保本地安装了 PostgreSQL，并导入了必要的表结构和数据（与 Python 版共用数据库）。
2.  **编译**: 运行 `mvn clean install`。
3.  **启动**: 运行 `BbaSimulationApplication` 主类。
4.  **触发计算**:
    - 系统启动时，`BbaRunner` (实现了 `CommandLineRunner`) 会自动运行。
    - 可以在 `BbaRunner.run()` 方法中修改 `policyNo` 和 `runDate` 参数。
    - 运行日志将输出到 `logs/` 目录下的 Markdown 文件中。

## 7. 开发规范

- **金额类型**: 所有金额计算强制使用 `java.math.BigDecimal`，禁止使用 `double`。
- **精度控制**: 除法运算需指定精度和舍入模式（通常为 `RoundingMode.HALF_UP`）。
- **日志**: 使用 `CalculationLogger` 记录详细的计算步骤，生成的日志结构与 Python 版一致，便于核对结果。
- **PV 字段访问**: 必须通过 `PVSourceData` 的 Getter 方法访问字段，禁止使用字符串硬编码。

---
**文档生成时间**: 2025-12-10
