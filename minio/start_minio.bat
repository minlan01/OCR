@echo off
set MINIO_ROOT_USER=minioadmin
set MINIO_ROOT_PASSWORD=minioadmin123
"E:\OCRScanStruct\minio\minio.exe" server E:\OCRScanStruct\minio\data --console-address :9001
