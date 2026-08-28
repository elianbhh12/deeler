# scripts/

Carpeta reservada para los scripts de subida directa a AWS que se van a
agregar más adelante:

- Subida de resultados a **S3** (los buckets que hoy solo se validan como
  texto en `s3_path`).
- Escritura/lectura en **DynamoDB** (las tablas asociadas a los eventos UDZ).

Todavía no hay nada acá. Cuando se agreguen, van a ser scripts independientes
de `app.py` (no forman parte del dashboard de validación) — probablemente uno
por tarea (`subir_s3.py`, `sincronizar_dynamo.py`, etc.), cada uno con su
propio `if __name__ == "__main__":` para poder correrlos sueltos o
encadenarlos desde un `.bat`.

Requisitos que van a hacer falta cuando esto se implemente (no instalados
todavía): `boto3` y credenciales de AWS con permisos de escritura en los
buckets/tablas correspondientes — separadas del `.env` de Azure DevOps que
usa `app.py`.
