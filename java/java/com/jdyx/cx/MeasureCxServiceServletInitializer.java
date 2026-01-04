package com.jdyx.cx;

//import com.zaxxer.hikari.HikariConfig;
//import com.zaxxer.hikari.HikariDataSource;
//import java.sql.ResultSet;
//import java.sql.SQLException;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.boot.web.servlet.support.SpringBootServletInitializer;
//import tech.tablesaw.api.Table;
//import tech.tablesaw.io.jdbc.SqlResultSetReader;

/**
 * web容器中进行部署
 *
 * @author lm.
 */
public class MeasureCxServiceServletInitializer extends SpringBootServletInitializer {

  @Override
  protected SpringApplicationBuilder configure(SpringApplicationBuilder application) {
    return application.sources(MeasureCxServiceServletInitializer.class);
  }
/*
  public static void main(String[] args) throws SQLException {

// 使用HikariCP连接池
    HikariConfig config = new HikariConfig();
    config.setJdbcUrl(url);
    config.setUsername(user);
    config.setPassword(password);

    try (HikariDataSource ds = new HikariDataSource(config)) {
      ResultSet resultSet = ds.getConnection().createStatement().executeQuery("SELECT * FROM products");
      Table result = SqlResultSetReader.read(resultSet);
      result.stream().
    }

// 避免在内存中过滤
    Table t = SqlResultSetReader.read(conn,
      "SELECT * FROM sales WHERE amount > 1000");
  }

 */

}
