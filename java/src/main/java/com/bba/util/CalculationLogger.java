package com.bba.util;

import lombok.extern.slf4j.Slf4j;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStreamWriter;
import java.io.PrintWriter;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.text.DecimalFormat;
import java.util.Map;

@Slf4j
public class CalculationLogger {

    private PrintWriter writer;
    private final DecimalFormat df = new DecimalFormat("#,##0.00");
    private final DecimalFormat df4 = new DecimalFormat("#,##0.0000");

    public CalculationLogger(String filePath) {
        if (filePath != null) {
            try {
                // Use UTF-8 explicitly
                writer = new PrintWriter(new OutputStreamWriter(new FileOutputStream(filePath), StandardCharsets.UTF_8));
            } catch (IOException e) {
                log.error("Failed to create log file: {}", e.getMessage());
            }
        }
    }

    public void logSection(String title) {
        logText("\n# " + title + "\n");
    }

    public void logText(String text) {
        if (writer != null) {
            writer.println(text);
            writer.flush();
        }
        log.info(text);
    }

    public void logItem(String title, String description, String formula, Map<String, Object> variables, Object result, String note) {
        if (writer == null) return;

        writer.println("### " + title);
        writer.println("- **说明**: " + description);
        writer.println("- **公式**: `" + formula + "`");
        
        if (variables != null && !variables.isEmpty()) {
            writer.println("- **变量**:");
            for (Map.Entry<String, Object> entry : variables.entrySet()) {
                String valStr = formatValue(entry.getValue());
                writer.println("  - " + entry.getKey() + ": " + valStr);
            }
        }
        
        String resStr = formatValue(result);
        writer.println("- **结果**: **" + resStr + "**");
        
        if (note != null && !note.isEmpty()) {
            writer.println("- **备注**: " + note);
        }
        writer.println();
        writer.flush();
    }
    
    private String formatValue(Object value) {
        if (value instanceof BigDecimal) {
            return df.format(value);
        }
        return String.valueOf(value);
    }

    public void close() {
        if (writer != null) {
            writer.close();
        }
    }
}
