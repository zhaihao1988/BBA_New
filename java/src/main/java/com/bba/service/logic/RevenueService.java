package com.bba.service.logic;

import com.bba.model.CalculationContext;
import com.bba.model.pv.PVSourceData;
import com.bba.util.CalculationLogger;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;

/**
 * Revenue calculation aligned with Python revenue.py:
 * - CSM/IACF 摊销保持原符号（通常为负，表示收入）
 * - 经验调整 = 保费经验调整 + IACF经验调整
 * - 总收入 = 赔付与费用净额 + RA释放净额 + CSM摊销 + IACF摊销 + 经验调整
 * 注：当前 Java 侧尚未落地赔付/RA明细，缺失时按0处理，避免Null。
 */
@Service
public class RevenueService {

    public void run(CalculationContext context, CalculationLogger logger) {
        BigDecimal zero = BigDecimal.ZERO;

        // === 预期赔付与维费（含亏损分摊） ===
        PVSourceData pvData = context.getPvSourceData() != null
                ? context.getPvSourceData().getData(context.getValMonthStr())
                : null;

        // IF 当前期（Cca，Wlk）
        BigDecimal pvClaimsIf = nvl(pvData != null ? pvData.getPvIfBopCcaRepWlkClaAmt() : null, zero);
        BigDecimal pvMaintIf = nvl(pvData != null ? pvData.getPvIfBopCcaRepWlkMtnAmt() : null, zero);
        // NB 当前期（Cca，Wlk）
        BigDecimal pvClaimsNb = nvl(pvData != null ? pvData.getPvNbIniCcaRepWlkClaAmt() : null, zero);
        BigDecimal pvMaintNb = nvl(pvData != null ? pvData.getPvNbIniCcaRepWlkMtnAmt() : null, zero);

        BigDecimal revenueClaimsExpensesGross = pvClaimsIf.add(pvMaintIf).add(pvClaimsNb).add(pvMaintNb);

        // 亏损分摊：分摊LC预期现金流 + LC调整预期现金流
        BigDecimal allocatedLcCf = nvl(context.getAllocatedLcCf(), zero);
        BigDecimal lcAdjustCf = nvl(context.getLcAdjustCf(), zero);
        BigDecimal revenueClaimsExpensesLcAlloc = allocatedLcCf.add(lcAdjustCf);
        BigDecimal revenueClaimsExpensesNet = revenueClaimsExpensesGross.subtract(allocatedLcCf);

        context.setRevenueClaimsExpensesGross(revenueClaimsExpensesGross);
        context.setRevenueClaimsExpensesLcAlloc(revenueClaimsExpensesLcAlloc);
        context.setRevenueClaimsExpensesNet(revenueClaimsExpensesNet);

        // === RA释放（含亏损分摊） ===
        BigDecimal raReleaseIf = nvl(pvData != null ? pvData.getPvIfBopCcaRepWlkRadAmt() : null, zero);
        BigDecimal raReleaseNb = nvl(pvData != null ? pvData.getPvNbIniCcaRepWlkRadAmt() : null, zero);
        BigDecimal raReleaseGross = raReleaseIf.add(raReleaseNb);

        BigDecimal allocatedLcRa = nvl(context.getAllocatedLcRa(), zero);
        BigDecimal lcAdjustRa = nvl(context.getLcAdjustRa(), zero);
        BigDecimal raReleaseLcAlloc = allocatedLcRa.add(lcAdjustRa);
        BigDecimal raReleaseNet = raReleaseGross.subtract(allocatedLcRa);

        context.setRaReleaseGross(raReleaseGross);
        context.setRaReleaseLcAlloc(raReleaseLcAlloc);
        context.setRaReleaseNet(raReleaseNet);

        // CSM/IACF摊销保持原符号，不取绝对值
        BigDecimal revenueCsmAmort = defaultVal(context.getCsmAmortAmount(), zero);
        BigDecimal revenueIacfAmort = defaultVal(context.getIacfAmortAmount(), zero);

        // 经验调整：保费 + IACF 经验调整
        BigDecimal premVar = defaultVal(context.getPremVar(), zero);
        BigDecimal iacfVar = defaultVal(context.getIacfVar(), zero);
        BigDecimal revenueExpAdj = premVar.add(iacfVar);

        // 汇总总收入
        BigDecimal totalRevenue = revenueClaimsExpensesNet
                .add(raReleaseNet)
                .add(revenueCsmAmort)
                .add(revenueIacfAmort)
                .add(revenueExpAdj);

        context.setRevenueClaimsExpensesNet(revenueClaimsExpensesNet);
        context.setRaReleaseNet(raReleaseNet);
        context.setRevenueIacfAmort(revenueIacfAmort);
        context.setRevenueExpAdj(revenueExpAdj);
        context.setTotalRevenue(totalRevenue);

        if (logger != null) {
            logger.logSection("Revenue (收入计算)");
            logger.logItem("保险合同收入_预期赔付与费用_含亏损", null, "IF/NB 预期当期赔付+维费（Wlk，Cca）", null, revenueClaimsExpensesGross, null);
            logger.logItem("保险合同收入_预期赔付与费用_亏损分摊", null, "LC分摊+LC调整（预期现金流）", null, revenueClaimsExpensesLcAlloc, null);
            logger.logItem("保险合同收入_摊销的CSM", null, "保持原符号（通常为负）", null, revenueCsmAmort, null);
            logger.logItem("保险合同收入_摊销的IACF", null, "保持原符号（通常为负）", null, revenueIacfAmort, null);
            logger.logItem("保险合同收入_经验调整", null, "保费经验调整 + IACF经验调整", null, revenueExpAdj, null);
            logger.logItem("保险合同收入_总计", null, "赔付/费用净额 + RA释放净额 + CSM摊销 + IACF摊销 + 经验调整", null, totalRevenue, null);
        }
    }

    private BigDecimal defaultVal(BigDecimal val, BigDecimal defVal) {
        return val != null ? val : defVal;
    }

    private BigDecimal nvl(BigDecimal val, BigDecimal defVal) {
        return val != null ? val : defVal;
    }
}

