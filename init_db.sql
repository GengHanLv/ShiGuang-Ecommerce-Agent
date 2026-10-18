-- 作用：首次启动 MySQL 容器时自动建表并插入模拟数据，用于订单查询功能演示
USE ecommerce;

CREATE TABLE products (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(200),
    price DECIMAL(10,2),
    stock INT,
    description TEXT
);

CREATE TABLE orders (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id VARCHAR(50),
    product_id INT,
    status VARCHAR(20),   -- pending, shipped, delivered, returned
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO products (name, price, stock, description) VALUES
('蓝牙耳机', 199.00, 100, '降噪蓝牙耳机，续航20小时'),
('机械键盘', 399.00, 50, '青轴87键');

INSERT INTO orders (user_id, product_id, status) VALUES
('user123', 1, 'shipped'),
('user123', 2, 'pending');