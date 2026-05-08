-- =====================================================================
-- Mortgage demo schema for AI Optimizer
-- Run as the schema owner (e.g. BANKDEMO). Drops and recreates everything.
-- Fully synthetic data — no real customers, no PII.
-- =====================================================================

-- Drop in dependency order (ignore errors on first run)
BEGIN
    FOR t IN (SELECT table_name FROM user_tables
              WHERE table_name IN ('PAYMENTS','MORTGAGES','PROPERTIES','CUSTOMERS','MORTGAGE_PRODUCTS'))
    LOOP
        EXECUTE IMMEDIATE 'DROP TABLE ' || t.table_name || ' CASCADE CONSTRAINTS PURGE';
    END LOOP;
END;
/

-- =====================================================================
-- Tables
-- =====================================================================

CREATE TABLE mortgage_products (
    product_code      VARCHAR2(20)  PRIMARY KEY,
    product_name      VARCHAR2(100) NOT NULL,
    rate_type         VARCHAR2(10)  NOT NULL,
    term_years        NUMBER(2)     NOT NULL,
    base_rate_pct     NUMBER(5,3)   NOT NULL,
    min_credit_score  NUMBER(3)     NOT NULL,
    max_ltv_pct       NUMBER(5,2)   NOT NULL
);

CREATE TABLE customers (
    customer_id    NUMBER         PRIMARY KEY,
    full_name      VARCHAR2(100)  NOT NULL,
    dob            DATE           NOT NULL,
    credit_score   NUMBER(3)      NOT NULL,
    annual_income  NUMBER(12,2)   NOT NULL,
    state          VARCHAR2(2)    NOT NULL
);

CREATE TABLE properties (
    property_id      NUMBER        PRIMARY KEY,
    street           VARCHAR2(120) NOT NULL,
    city             VARCHAR2(60)  NOT NULL,
    state            VARCHAR2(2)   NOT NULL,
    appraised_value  NUMBER(12,2)  NOT NULL,
    property_type    VARCHAR2(20)  NOT NULL
);

CREATE TABLE mortgages (
    mortgage_id       NUMBER        PRIMARY KEY,
    customer_id       NUMBER        NOT NULL REFERENCES customers,
    property_id       NUMBER        NOT NULL REFERENCES properties,
    product_code      VARCHAR2(20)  NOT NULL REFERENCES mortgage_products,
    principal         NUMBER(12,2)  NOT NULL,
    interest_rate     NUMBER(5,3)   NOT NULL,
    term_years        NUMBER(2)     NOT NULL,
    origination_date  DATE          NOT NULL,
    status            VARCHAR2(15)  NOT NULL
);

CREATE TABLE payments (
    payment_id         NUMBER       PRIMARY KEY,
    mortgage_id        NUMBER       NOT NULL REFERENCES mortgages,
    payment_date       DATE         NOT NULL,
    amount             NUMBER(10,2) NOT NULL,
    principal_portion  NUMBER(10,2) NOT NULL,
    interest_portion   NUMBER(10,2) NOT NULL
);

CREATE INDEX ix_mortgages_customer ON mortgages(customer_id);
CREATE INDEX ix_mortgages_product  ON mortgages(product_code);
CREATE INDEX ix_mortgages_status   ON mortgages(status);
CREATE INDEX ix_payments_mortgage  ON payments(mortgage_id);

-- Comments help NL2SQL pick the right columns and values.
COMMENT ON TABLE  mortgage_products       IS 'Catalog of mortgage products offered by the bank.';
COMMENT ON COLUMN mortgage_products.rate_type        IS 'Rate type: FIXED or ARM (adjustable).';
COMMENT ON COLUMN mortgage_products.min_credit_score IS 'Minimum FICO credit score required by underwriting policy.';
COMMENT ON COLUMN mortgage_products.max_ltv_pct      IS 'Maximum loan-to-value ratio allowed, as a percent.';

COMMENT ON TABLE  customers              IS 'Bank mortgage customers (synthetic demo data).';
COMMENT ON COLUMN customers.credit_score IS 'Most recent FICO credit score (300-850). May differ from score at mortgage origination.';
COMMENT ON COLUMN customers.annual_income IS 'Most recent reported annual gross income in USD.';

COMMENT ON TABLE  mortgages              IS 'Active and historical mortgage loans issued to customers.';
COMMENT ON COLUMN mortgages.status       IS 'Loan status. Allowed values: ACTIVE (currently being paid), PAID_OFF (fully repaid), DEFAULTED (in default).';
COMMENT ON COLUMN mortgages.product_code IS 'Mortgage product. Joins to mortgage_products.product_code.';
COMMENT ON COLUMN mortgages.interest_rate IS 'Note rate at origination, as a percent (e.g. 6.875 means 6.875%).';

COMMENT ON TABLE  properties             IS 'Properties securing the mortgage loans.';

-- =====================================================================
-- Seed: products
-- =====================================================================
INSERT INTO mortgage_products VALUES ('FIXED30-PRIME', '30-Year Fixed Prime',          'FIXED', 30, 6.500, 720, 80.00);
INSERT INTO mortgage_products VALUES ('ARM5_1-STD',    '5/1 Adjustable-Rate Standard', 'ARM',   30, 5.875, 680, 85.00);
INSERT INTO mortgage_products VALUES ('JUMBO15-PRIME', '15-Year Jumbo Prime',          'FIXED', 15, 6.250, 760, 75.00);
INSERT INTO mortgage_products VALUES ('FHA-30YR',      '30-Year FHA',                  'FIXED', 30, 6.750, 580, 96.50);

-- =====================================================================
-- Seed: customers (30 rows)
--   Credit-score distribution is intentional. Customers 5, 11, 18, 22
--   currently hold ACTIVE FIXED30-PRIME loans but their CURRENT credit
--   score is below the 720 floor — these are the four the combined-mode
--   demo prompt should surface.
-- =====================================================================
INSERT INTO customers VALUES ( 1, 'Aisha Patel',       DATE '1985-03-12', 745, 185000.00, 'CA');
INSERT INTO customers VALUES ( 2, 'Marcus Chen',       DATE '1978-11-04', 802, 240000.00, 'WA');
INSERT INTO customers VALUES ( 3, 'Sofia Rodriguez',   DATE '1990-07-22', 692,  78000.00, 'TX');
INSERT INTO customers VALUES ( 4, 'James OBrien',      DATE '1972-01-30', 768, 165000.00, 'MA');
INSERT INTO customers VALUES ( 5, 'Linh Nguyen',       DATE '1988-05-18', 680,  95000.00, 'CA');
INSERT INTO customers VALUES ( 6, 'Devon Williams',    DATE '1983-09-09', 731, 108000.00, 'GA');
INSERT INTO customers VALUES ( 7, 'Priya Iyer',        DATE '1976-12-25', 815, 295000.00, 'NY');
INSERT INTO customers VALUES ( 8, 'Carlos Mendez',     DATE '1992-04-14', 658,  62000.00, 'FL');
INSERT INTO customers VALUES ( 9, 'Hannah Schmidt',    DATE '1980-08-03', 783, 145000.00, 'IL');
INSERT INTO customers VALUES (10, 'Rashid Karim',      DATE '1986-02-19', 742, 128000.00, 'VA');
INSERT INTO customers VALUES (11, 'Yuki Tanaka',       DATE '1989-10-07', 695,  72000.00, 'WA');
INSERT INTO customers VALUES (12, 'Benjamin Cohen',    DATE '1974-06-15', 779, 210000.00, 'NY');
INSERT INTO customers VALUES (13, 'Olivia Martinez',   DATE '1987-11-29', 720,  98000.00, 'CA');
INSERT INTO customers VALUES (14, 'Tyler Reeves',      DATE '1981-03-21', 751, 135000.00, 'TX');
INSERT INTO customers VALUES (15, 'Ngozi Okafor',      DATE '1979-07-11', 808, 267000.00, 'NY');
INSERT INTO customers VALUES (16, 'Diego Salazar',     DATE '1991-01-08', 645,  54000.00, 'AZ');
INSERT INTO customers VALUES (17, 'Emma Whitfield',    DATE '1984-05-26', 794, 178000.00, 'MA');
INSERT INTO customers VALUES (18, 'Noah Kim',          DATE '1990-09-13', 705,  89000.00, 'CA');
INSERT INTO customers VALUES (19, 'Isabella Romano',   DATE '1982-12-04', 762, 156000.00, 'IL');
INSERT INTO customers VALUES (20, 'Khalid Aziz',       DATE '1985-08-17', 738, 122000.00, 'TX');
INSERT INTO customers VALUES (21, 'Abigail Foster',    DATE '1973-04-02', 821, 310000.00, 'CT');
INSERT INTO customers VALUES (22, 'Ravi Sharma',       DATE '1988-10-23', 712,  84000.00, 'NJ');
INSERT INTO customers VALUES (23, 'Chloe Bennett',     DATE '1986-06-30', 749, 138000.00, 'CO');
INSERT INTO customers VALUES (24, 'Marcus Johnson',    DATE '1993-02-11', 615,  48000.00, 'OH');
INSERT INTO customers VALUES (25, 'Mei Lin',           DATE '1980-11-19', 786, 192000.00, 'CA');
INSERT INTO customers VALUES (26, 'Ahmed Hassan',      DATE '1977-05-05', 774, 164000.00, 'MI');
INSERT INTO customers VALUES (27, 'Layla Khan',        DATE '1989-08-28', 727, 103000.00, 'FL');
INSERT INTO customers VALUES (28, 'Samuel Park',       DATE '1975-12-16', 791, 228000.00, 'WA');
INSERT INTO customers VALUES (29, 'Tara OConnor',      DATE '1991-07-04', 668,  69000.00, 'PA');
INSERT INTO customers VALUES (30, 'Vincent Russo',     DATE '1976-09-22', 805, 246000.00, 'NY');

-- =====================================================================
-- Seed: properties (30 rows)
-- =====================================================================
INSERT INTO properties VALUES ( 1, '1247 Maple Street',    'San Francisco', 'CA',  980000.00, 'SFH');
INSERT INTO properties VALUES ( 2, '88 Pine Ave',          'Seattle',       'WA', 1250000.00, 'SFH');
INSERT INTO properties VALUES ( 3, '502 Oakwood Dr',       'Austin',        'TX',  385000.00, 'SFH');
INSERT INTO properties VALUES ( 4, '2199 Beacon Hill',     'Boston',        'MA',  890000.00, 'CONDO');
INSERT INTO properties VALUES ( 5, '76 Cedar Lane',        'San Jose',      'CA', 1450000.00, 'SFH');
INSERT INTO properties VALUES ( 6, '1812 Peachtree St',    'Atlanta',       'GA',  440000.00, 'TOWNHOUSE');
INSERT INTO properties VALUES ( 7, '25 Park Avenue',       'New York',      'NY', 2150000.00, 'CONDO');
INSERT INTO properties VALUES ( 8, '9931 Coral Way',       'Miami',         'FL',  310000.00, 'CONDO');
INSERT INTO properties VALUES ( 9, '4456 Lake Shore Dr',   'Chicago',       'IL',  675000.00, 'SFH');
INSERT INTO properties VALUES (10, '318 Henry Street',     'Arlington',     'VA',  710000.00, 'SFH');
INSERT INTO properties VALUES (11, '1567 Rainier Ave',     'Seattle',       'WA',  560000.00, 'TOWNHOUSE');
INSERT INTO properties VALUES (12, '14 Park Place',        'Brooklyn',      'NY',  920000.00, 'TOWNHOUSE');
INSERT INTO properties VALUES (13, '287 Sunset Blvd',      'Los Angeles',   'CA',  785000.00, 'SFH');
INSERT INTO properties VALUES (14, '6724 Lamar Blvd',      'Austin',        'TX',  520000.00, 'SFH');
INSERT INTO properties VALUES (15, '1 Central Park West',  'New York',      'NY', 3400000.00, 'CONDO');
INSERT INTO properties VALUES (16, '945 Grand Canyon Dr',  'Phoenix',       'AZ',  295000.00, 'SFH');
INSERT INTO properties VALUES (17, '100 Commonwealth Ave', 'Boston',        'MA', 1180000.00, 'CONDO');
INSERT INTO properties VALUES (18, '622 Mission St',       'San Diego',     'CA',  645000.00, 'TOWNHOUSE');
INSERT INTO properties VALUES (19, '405 Michigan Ave',     'Chicago',       'IL',  890000.00, 'CONDO');
INSERT INTO properties VALUES (20, '1733 South Lamar',     'Houston',       'TX',  410000.00, 'SFH');
INSERT INTO properties VALUES (21, '7 Greenwich Lane',     'Greenwich',     'CT', 2250000.00, 'SFH');
INSERT INTO properties VALUES (22, '56 Hudson Street',     'Hoboken',       'NJ',  620000.00, 'CONDO');
INSERT INTO properties VALUES (23, '982 Larimer St',       'Denver',        'CO',  725000.00, 'TOWNHOUSE');
INSERT INTO properties VALUES (24, '4501 Indianola Ave',   'Columbus',      'OH',  245000.00, 'SFH');
INSERT INTO properties VALUES (25, '3388 Mulholland Dr',   'Los Angeles',   'CA', 1340000.00, 'SFH');
INSERT INTO properties VALUES (26, '211 Woodward Ave',     'Detroit',       'MI',  385000.00, 'SFH');
INSERT INTO properties VALUES (27, '8800 Collins Ave',     'Miami',         'FL',  590000.00, 'CONDO');
INSERT INTO properties VALUES (28, '612 Olive Way',        'Bellevue',      'WA', 1620000.00, 'SFH');
INSERT INTO properties VALUES (29, '17 Rittenhouse Sq',    'Philadelphia',  'PA',  475000.00, 'CONDO');
INSERT INTO properties VALUES (30, '5 Riverside Dr',       'New York',      'NY', 1980000.00, 'CONDO');

-- =====================================================================
-- Seed: mortgages (36 rows)
--   Active FIXED30-PRIME mortgages whose CURRENT customer credit score
--   is below 720 (the policy floor): mortgage_id 5, 11, 18, 22
--   These are the four the combined-mode prompt should identify.
-- =====================================================================
-- Active FIXED30-PRIME (16 rows: 1, 4, 5, 6, 9, 11, 13, 14, 17, 18, 19, 20, 22, 23, 27, 30)
INSERT INTO mortgages VALUES ( 1,  1,  1, 'FIXED30-PRIME',  720000.00, 6.875, 30, DATE '2023-04-15', 'ACTIVE');
INSERT INTO mortgages VALUES ( 4,  4,  4, 'FIXED30-PRIME',  640000.00, 6.500, 30, DATE '2024-02-08', 'ACTIVE');
INSERT INTO mortgages VALUES ( 5,  5, 13, 'FIXED30-PRIME',  580000.00, 4.250, 30, DATE '2021-06-22', 'ACTIVE');
INSERT INTO mortgages VALUES ( 6,  6,  6, 'FIXED30-PRIME',  340000.00, 6.750, 30, DATE '2023-09-30', 'ACTIVE');
INSERT INTO mortgages VALUES ( 9,  9,  9, 'FIXED30-PRIME',  510000.00, 5.875, 30, DATE '2022-11-17', 'ACTIVE');
INSERT INTO mortgages VALUES (11, 11, 11, 'FIXED30-PRIME',  430000.00, 3.125, 30, DATE '2020-08-04', 'ACTIVE');
INSERT INTO mortgages VALUES (13, 13, 18, 'FIXED30-PRIME',  475000.00, 7.000, 30, DATE '2024-05-13', 'ACTIVE');
INSERT INTO mortgages VALUES (14, 14, 14, 'FIXED30-PRIME',  410000.00, 6.625, 30, DATE '2023-07-19', 'ACTIVE');
INSERT INTO mortgages VALUES (17, 17, 17, 'FIXED30-PRIME',  890000.00, 6.500, 30, DATE '2024-01-26', 'ACTIVE');
INSERT INTO mortgages VALUES (18, 18, 25, 'FIXED30-PRIME',  680000.00, 4.000, 30, DATE '2021-03-09', 'ACTIVE');
INSERT INTO mortgages VALUES (19, 19, 19, 'FIXED30-PRIME',  720000.00, 6.250, 30, DATE '2023-12-05', 'ACTIVE');
INSERT INTO mortgages VALUES (20, 20, 20, 'FIXED30-PRIME',  330000.00, 6.875, 30, DATE '2024-03-22', 'ACTIVE');
INSERT INTO mortgages VALUES (22, 22, 22, 'FIXED30-PRIME',  495000.00, 3.250, 30, DATE '2020-11-30', 'ACTIVE');
INSERT INTO mortgages VALUES (23, 23, 23, 'FIXED30-PRIME',  580000.00, 6.500, 30, DATE '2024-04-11', 'ACTIVE');
INSERT INTO mortgages VALUES (27, 27, 27, 'FIXED30-PRIME',  470000.00, 6.750, 30, DATE '2023-10-08', 'ACTIVE');
INSERT INTO mortgages VALUES (30, 30, 30, 'FIXED30-PRIME', 1500000.00, 6.500, 30, DATE '2024-06-14', 'ACTIVE');

-- Active ARM5_1-STD (3 rows)
INSERT INTO mortgages VALUES ( 3,  3,  3, 'ARM5_1-STD',     310000.00, 5.875, 30, DATE '2024-03-04', 'ACTIVE');
INSERT INTO mortgages VALUES (10, 10, 10, 'ARM5_1-STD',     560000.00, 5.625, 30, DATE '2023-06-28', 'ACTIVE');
INSERT INTO mortgages VALUES (26, 26, 26, 'ARM5_1-STD',     290000.00, 5.875, 30, DATE '2024-04-29', 'ACTIVE');

-- Active JUMBO15-PRIME (6 rows)
INSERT INTO mortgages VALUES ( 2,  2,  2, 'JUMBO15-PRIME',  920000.00, 6.125, 15, DATE '2023-05-12', 'ACTIVE');
INSERT INTO mortgages VALUES ( 7,  7,  7, 'JUMBO15-PRIME', 1620000.00, 6.000, 15, DATE '2023-08-21', 'ACTIVE');
INSERT INTO mortgages VALUES (15, 15, 15, 'JUMBO15-PRIME', 2400000.00, 6.250, 15, DATE '2024-01-15', 'ACTIVE');
INSERT INTO mortgages VALUES (21, 21, 21, 'JUMBO15-PRIME', 1700000.00, 6.000, 15, DATE '2023-11-02', 'ACTIVE');
INSERT INTO mortgages VALUES (25, 25,  5, 'JUMBO15-PRIME', 1080000.00, 6.250, 15, DATE '2024-02-27', 'ACTIVE');
INSERT INTO mortgages VALUES (28, 28, 28, 'JUMBO15-PRIME', 1250000.00, 6.125, 15, DATE '2023-12-19', 'ACTIVE');

-- Active FHA-30YR (4 rows)
INSERT INTO mortgages VALUES ( 8,  8,  8, 'FHA-30YR',       290000.00, 6.875, 30, DATE '2024-02-15', 'ACTIVE');
INSERT INTO mortgages VALUES (16, 16, 16, 'FHA-30YR',       275000.00, 6.750, 30, DATE '2023-10-20', 'ACTIVE');
INSERT INTO mortgages VALUES (24, 24, 24, 'FHA-30YR',       225000.00, 7.000, 30, DATE '2024-05-06', 'ACTIVE');
INSERT INTO mortgages VALUES (29, 29, 29, 'FHA-30YR',       430000.00, 6.875, 30, DATE '2024-03-30', 'ACTIVE');

-- Defaulted (1 row)
INSERT INTO mortgages VALUES (12, 12, 12, 'JUMBO15-PRIME',  830000.00, 6.500, 15, DATE '2022-04-18', 'DEFAULTED');

-- Paid-off (5 rows)
INSERT INTO mortgages VALUES (31,  1, 11, 'ARM5_1-STD',     420000.00, 3.500, 30, DATE '2018-06-12', 'PAID_OFF');
INSERT INTO mortgages VALUES (32,  4, 21, 'FIXED30-PRIME',  660000.00, 3.875, 30, DATE '2017-09-04', 'PAID_OFF');
INSERT INTO mortgages VALUES (33,  9, 24, 'FHA-30YR',       180000.00, 4.250, 30, DATE '2016-11-23', 'PAID_OFF');
INSERT INTO mortgages VALUES (34, 21, 29, 'FIXED30-PRIME',  390000.00, 4.000, 30, DATE '2017-02-08', 'PAID_OFF');
INSERT INTO mortgages VALUES (35, 12,  4, 'ARM5_1-STD',     510000.00, 3.625, 30, DATE '2018-08-15', 'PAID_OFF');

-- =====================================================================
-- Seed: payments (a representative sample, not full amortization)
-- =====================================================================
INSERT INTO payments VALUES (1,   1, DATE '2024-09-01', 4729.45, 1183.20, 3546.25);
INSERT INTO payments VALUES (2,   1, DATE '2024-10-01', 4729.45, 1190.00, 3539.45);
INSERT INTO payments VALUES (3,   1, DATE '2024-11-01', 4729.45, 1196.81, 3532.64);
INSERT INTO payments VALUES (4,   4, DATE '2024-09-01', 4046.39, 1281.06, 2765.33);
INSERT INTO payments VALUES (5,   4, DATE '2024-10-01', 4046.39, 1287.99, 2758.40);
INSERT INTO payments VALUES (6,   5, DATE '2024-09-01', 2853.21, 1808.36, 1044.85);
INSERT INTO payments VALUES (7,   5, DATE '2024-10-01', 2853.21, 1814.76, 1038.45);
INSERT INTO payments VALUES (8,   9, DATE '2024-09-01', 3017.21, 1067.10, 1950.11);
INSERT INTO payments VALUES (9,   9, DATE '2024-10-01', 3017.21, 1072.32, 1944.89);
INSERT INTO payments VALUES (10, 11, DATE '2024-09-01', 1843.20,  961.45,  881.75);
INSERT INTO payments VALUES (11, 11, DATE '2024-10-01', 1843.20,  963.96,  879.24);
INSERT INTO payments VALUES (12, 13, DATE '2024-09-01', 3160.84,  391.42, 2769.42);
INSERT INTO payments VALUES (13, 13, DATE '2024-10-01', 3160.84,  393.70, 2767.14);
INSERT INTO payments VALUES (14, 17, DATE '2024-09-01', 5625.31, 1804.94, 3820.37);
INSERT INTO payments VALUES (15, 18, DATE '2024-09-01', 3246.85, 1003.18, 2243.67);
INSERT INTO payments VALUES (16, 22, DATE '2024-09-01', 2155.43,  814.99, 1340.44);
INSERT INTO payments VALUES (17, 30, DATE '2024-09-01', 9479.50, 3354.50, 6125.00);
INSERT INTO payments VALUES (18,  2, DATE '2024-09-01', 7800.41, 3105.16, 4695.25);
INSERT INTO payments VALUES (19,  7, DATE '2024-09-01',13660.00, 5560.00, 8100.00);
INSERT INTO payments VALUES (20, 15, DATE '2024-09-01',20580.00, 8080.00,12500.00);

COMMIT;

-- =====================================================================
-- Sanity: print expected counts so you can verify after running the script
-- =====================================================================
PROMPT
PROMPT === Verify expected counts ===
SELECT product_code, status, COUNT(*) AS n, ROUND(AVG(interest_rate),3) AS avg_rate
FROM   mortgages
GROUP  BY product_code, status
ORDER  BY product_code, status;

PROMPT
PROMPT === Combined-mode prompt expected answer: 4 customers ===
SELECT m.mortgage_id, c.customer_id, c.full_name, c.credit_score
FROM   mortgages m JOIN customers c ON c.customer_id = m.customer_id
WHERE  m.product_code = 'FIXED30-PRIME'
  AND  m.status       = 'ACTIVE'
  AND  c.credit_score < (SELECT min_credit_score FROM mortgage_products WHERE product_code = 'FIXED30-PRIME')
ORDER  BY c.credit_score;

COMMIT;