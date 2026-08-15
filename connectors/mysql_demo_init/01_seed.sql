-- Simula un ERP externo (ej. el sistema de la sede que se acaba de
-- incorporar en Arequipa) que vive en su propio MySQL, separado del
-- Postgres del CMMS. Se auto-ejecuta la primera vez que arranca el
-- contenedor mysql_demo (docker-entrypoint-initdb.d).
--
-- Este es el escenario que demuestra `connectors/sql_connector.py`:
-- migrar datos de un motor de base de datos DISTINTO (MySQL) hacia el
-- Postgres del CMMS, usando el mismo motor ETL / mismo postgres_loader.

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS equipos_erp (
    id            INT PRIMARY KEY AUTO_INCREMENT,
    codigo        VARCHAR(50) NOT NULL UNIQUE,
    nombre        VARCHAR(200) NOT NULL,
    fabricante    VARCHAR(100),
    modelo        VARCHAR(100),
    ubicacion     VARCHAR(200),
    criticidad    VARCHAR(20),
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO equipos_erp (codigo, nombre, fabricante, modelo, ubicacion, criticidad, updated_at) VALUES
('AQP-001', 'Grupo Electrógeno Diesel', 'Cummins', 'C150D5', 'CLINICA_INTL/Sede_Arequipa/Sala_de_Maquinas', 'Muy Alta', NOW()),
('AQP-002', 'Chiller de Climatización', 'Carrier', '30XA-502', 'CLINICA_INTL/Sede_Arequipa/Azotea_Tecnica', 'Alta', NOW()),
('AQP-003', 'Bomba de Vacío Central', 'Becker', 'VT4.40', 'CLINICA_INTL/Sede_Arequipa/Central_Gases_Medicinales', 'Muy Alta', NOW()),
('AQP-004', 'Tablero Eléctrico Principal', 'Schneider Electric', 'PrismaSet', 'CLINICA_INTL/Sede_Arequipa/Sala_de_Tableros', 'Alta', NOW()),
('AQP-005', 'Torre de Enfriamiento', 'BAC', 'S1500A', 'CLINICA_INTL/Sede_Arequipa/Azotea_Tecnica', 'Media', NOW()),
('AQP-006', 'UPS Sistema de Energía Ininterrumpida', 'APC', 'Symmetra PX 160kW', 'CLINICA_INTL/Sede_Arequipa/Sala_de_Tableros', 'Muy Alta', NOW());
