package com.bba.service;

import com.bba.entity.PolicyContract;
import com.bba.model.CalculationContext;
import com.bba.util.CalculationLogger;
import org.springframework.stereotype.Service;

import java.io.BufferedWriter;
import java.io.FileWriter;
import java.io.IOException;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

/**
 * Batch runner to mirror Python run_batch_process_assumption.py:
 * - policyNo 优先，其次 limit 取前N条保单
 * - 输出 CSV 字段符号与 Python 一致（CSM/IACF 摊销保留负号；LC 显示原符号）
 */
@Service
public class BatchAssumptionService {

    private final DataLoaderService dataLoaderService;
    private final LifecycleSimulationService lifecycleSimulationService;

    public BatchAssumptionService(DataLoaderService dataLoaderService,
                                  LifecycleSimulationService lifecycleSimulationService) {
        this.dataLoaderService = dataLoaderService;
        this.lifecycleSimulationService = lifecycleSimulationService;
    }

    public void run(String policyNo, int limit, String valMonth, String outPath) {
        List<String> policyNos = new ArrayList<>();
        if (policyNo != null && !policyNo.isEmpty()) {
            policyNos.add(policyNo);
        } else {
            List<PolicyContract> list = dataLoaderService.listPolicyLimited(limit > 0 ? limit : 100);
            for (PolicyContract pc : list) {
                policyNos.add(pc.getPolicyNo());
            }
        }

        try (BufferedWriter writer = new BufferedWriter(new FileWriter(outPath))) {
            // Header 完全对齐 Python run_batch_process_assumption.py RESULT_COLUMNS
            writer.write(String.join(",",
                    "policy_no",
                    "certi_no",
                    "year",
                    "保险合同收入_预期赔付与费用_含亏损",
                    "保险合同收入_预期赔付与费用_亏损分摊",
                    "保险合同收入_预期释放的非金融风险调整_含亏损",
                    "保险合同收入_预期释放的非金融风险调整_亏损分摊",
                    "保险合同收入_摊销的CSM",
                    "保险合同收入_摊销的IACF",
                    "保险合同收入_经验调整",
                    "赔付与费用_亏损分摊_预期现金流",
                    "赔付与费用_亏损分摊_非金融风险调整",
                    "赔付与费用_摊销的IACF",
                    "亏损合同损益_新增合同预期现金流_赔付与费用现金流_亏损",
                    "亏损合同损益_新增合同非金融风险调整_亏损",
                    "亏损合同损益_不调整CSM的预期现金流变动",
                    "亏损合同损益_不调整CSM的非金融风险调整变动",
                    "IFIE_P&L_未到期_预期现金流_非亏损",
                    "IFIE_P&L_未到期_预期现金流_亏损",
                    "IFIE_P&L_未到期_非金融风险调整_非亏损",
                    "IFIE_P&L_未到期_非金融风险调整_亏损",
                    "IFIE_P&L_未到期_CSM",
                    "IFIE_OCI_未到期_预期现金流_非亏损",
                    "IFIE_OCI_未到期_预期现金流_亏损",
                    "IFIE_OCI_未到期_非金融风险调整_非亏损",
                    "IFIE_OCI_未到期_非金融风险调整_亏损",
                    "未到期责任负债_预期现金流_非亏损",
                    "未到期责任负债_预期现金流_亏损",
                    "未到期责任负债_非金融风险调整_非亏损",
                    "未到期责任负债_非金融风险调整_亏损",
                    "未到期责任负债_CSM",
                    "未到期_调整CSM的预期现金流变动",
                    "未到期_调整CSM的非金融风险调整变动",
                    "未到期_调整CSM的估计变更",
                    "新增合同预期现金流_保费现金流_盈利合同",
                    "新增合同预期现金流_IACF_盈利合同",
                    "新增合同预期现金流_赔付与费用现金流_盈利合同",
                    "新增合同非金融风险调整_盈利合同",
                    "新增合同CSM_盈利合同",
                    "新增合同预期现金流_保费现金流_亏损合同",
                    "新增合同预期现金流_IACF_亏损合同",
                    "新增合同预期现金流_赔付与费用现金流_亏损合同_非亏损",
                    "新增合同非金融风险调整_亏损合同_非亏损",
                    "现金流_收到的保费",
                    "现金流_支付的获取费用"
            ));
            writer.newLine();

            for (String pn : policyNos) {
                try {
                    CalculationLogger logger = null; // 批量不输出日志文件
                    lifecycleSimulationService.runSimulation(pn, null, valMonth);
                    CalculationContext ctx = lifecycleSimulationService.getLastContext();
                    if (ctx == null) continue;

                    // Python 导出时对 “保险合同收入_摊销的CSM” 与 “IFIE_P&L_未到期_CSM” 做了取反，这里同步
                    BigDecimal csmAmortForExport = ctx.getCsmAmortAmount() != null ? ctx.getCsmAmortAmount().negate() : BigDecimal.ZERO;
                    BigDecimal ifiePlCsmForExport = ctx.getIfiePlLc() != null ? ctx.getIfiePlLc().negate() : BigDecimal.ZERO; // 以LC部分代表CSM分摊的IFIE，若无则0

                    String[] row = new String[]{
                            pn,
                            safe(ctx.getCertiNo()),
                            safeInt(ctx.getYear()),
                            fmt(z(ctx.getRevenueClaimsExpensesGross())),
                            fmt(z(ctx.getRevenueClaimsExpensesLcAlloc())),
                            fmt(z(ctx.getRaReleaseGross())),
                            fmt(z(ctx.getRaReleaseLcAlloc())),
                            fmt(csmAmortForExport),
                            fmt(z(ctx.getIacfAmortAmount())),
                            fmt(z(ctx.getRevenueExpAdj())),
                            fmt(z(ctx.getAllocatedLcCf())),
                            fmt(z(ctx.getAllocatedLcRa())),
                            fmt(z(ctx.getIacfAmortAmount())),
                            fmt(BigDecimal.ZERO), // 亏损合同损益_新增合同预期现金流_赔付与费用现金流_亏损
                            fmt(BigDecimal.ZERO), // 亏损合同损益_新增合同非金融风险调整_亏损
                            fmt(BigDecimal.ZERO), // 亏损合同损益_不调整CSM的预期现金流变动
                            fmt(BigDecimal.ZERO), // 亏损合同损益_不调整CSM的非金融风险调整变动
                            fmt(z(ctx.getIfiePlNonLc())),
                            fmt(z(ctx.getIfiePlLc())),
                            fmt(z(ctx.getIfieOciNonLc())),
                            fmt(z(ctx.getIfieOciLc())),
                            fmt(ifiePlCsmForExport),
                            fmt(z(ctx.getIfieOciNonLc())),
                            fmt(z(ctx.getIfieOciLc())),
                            fmt(z(ctx.getIfieOciNonLc())),
                            fmt(z(ctx.getIfieOciLc())),
                            fmt(BigDecimal.ZERO), // 未到期责任负债_预期现金流_非亏损
                            fmt(BigDecimal.ZERO), // 未到期责任负债_预期现金流_亏损
                            fmt(BigDecimal.ZERO), // 未到期责任负债_非金融风险调整_非亏损
                            fmt(BigDecimal.ZERO), // 未到期责任负债_非金融风险调整_亏损
                            fmt(z(ctx.getEndCsmBeforeAmort())), // 未到期责任负债_CSM
                            fmt(BigDecimal.ZERO), // 未到期_调整CSM的预期现金流变动
                            fmt(BigDecimal.ZERO), // 未到期_调整CSM的非金融风险调整变动
                            fmt(BigDecimal.ZERO), // 未到期_调整CSM的估计变更
                            fmt(BigDecimal.ZERO), // 新增合同预期现金流_保费现金流_盈利合同
                            fmt(BigDecimal.ZERO), // 新增合同预期现金流_IACF_盈利合同
                            fmt(BigDecimal.ZERO), // 新增合同预期现金流_赔付与费用现金流_盈利合同
                            fmt(BigDecimal.ZERO), // 新增合同非金融风险调整_盈利合同
                            fmt(z(ctx.getNbInitialCsm())), // 新增合同CSM_盈利合同
                            fmt(BigDecimal.ZERO), // 新增合同预期现金流_保费现金流_亏损合同
                            fmt(BigDecimal.ZERO), // 新增合同预期现金流_IACF_亏损合同
                            fmt(BigDecimal.ZERO), // 新增合同预期现金流_赔付与费用现金流_亏损合同_非亏损
                            fmt(BigDecimal.ZERO), // 新增合同非金融风险调整_亏损合同_非亏损
                            fmt(z(ctx.getActualPremium())),
                            fmt(z(ctx.getActualIacfIncurred()))
                    };
                    writer.write(String.join(",", row));
                    writer.newLine();
                } catch (Exception ex) {
                    // skip this policy, continue next
                }
            }
        } catch (IOException e) {
            throw new RuntimeException("写CSV失败: " + e.getMessage(), e);
        }
    }

    private String fmt(BigDecimal val) {
        return val == null ? "" : val.toPlainString();
    }

    private BigDecimal z(BigDecimal val) {
        return val == null ? BigDecimal.ZERO : val;
    }
}

