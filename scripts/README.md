# scripts/

Carpeta reservada para scripts sueltos de mantenimiento (uso puntual desde
línea de comandos, no parte del dashboard).

**La subida a AWS (DynamoDB) no vive acá** — quedó integrada directamente al
dashboard en `core/aws_upload.py` (lógica) + `ui/aws_console.py` (la consola,
sección "Subir a AWS" al final de la página). Se decidió así en vez de un
script aparte porque necesita el TA/AID/UDZ que ya resolvió `analizar_hu()`
para esa HU puntual (no un escaneo de carpeta como el `cargaaws.py`
original), y feedback en vivo en la UI — ver la sección "Subida a AWS" en el
`README.md` de la raíz para el detalle completo (credenciales, tablas,
partition keys).

Si en el futuro hace falta un script de subida a **S3** (bucket de
resultados/crudos, hoy solo se valida el `s3_path` como texto, no se escribe
nada), ese sí puede vivir acá, siguiendo el mismo patrón que
`core/aws_upload.py`: `boto3`, credenciales en `aws_credentials.json`, con
`if __name__ == "__main__":` para poder correrlo suelto.
