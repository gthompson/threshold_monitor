CREATE DATABASE pipeline;
CREATE TABLE pipeline.occ_display (station_id INT, low BOOLEAN, med BOOLEAN, high BOOLEAN, system_status BOOLEAN);
INSERT INTO pipeline.occ_display VALUES (1, 0, 0, 0, 1);
INSERT INTO pipeline.occ_display VALUES (2, 0, 0, 0, 1);
INSERT INTO pipeline.occ_display VALUES (3, 0, 0, 0, 1);
INSERT INTO pipeline.occ_display VALUES (4, 0, 0, 0, 1);
INSERT INTO pipeline.occ_display VALUES (5, 0, 0, 0, 1);
INSERT INTO pipeline.occ_display VALUES (6, 0, 0, 0, 1);
INSERT INTO pipeline.occ_display VALUES (7, 0, 0, 0, 1);
INSERT INTO pipeline.occ_display VALUES (8, 0, 0, 0, 1);
INSERT INTO pipeline.occ_display VALUES (9, 0, 0, 0, 1);
INSERT INTO pipeline.occ_display VALUES (10, 0, 0, 0, 1);
INSERT INTO pipeline.occ_display VALUES (11, 0, 0, 0, 1);
INSERT INTO pipeline.occ_display VALUES (12, 0, 0, 0, 1);
INSERT INTO pipeline.occ_display VALUES (13, 0, 0, 0, 1);
CREATE USER 'pipe' IDENTIFIED BY 'VMP1PA3CAk'