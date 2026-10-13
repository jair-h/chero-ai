"""Paquete de integraciones de Tentakl.

Capa de conexión con servicios externos (tiendas, analytics, ads).
Mantiene la lógica de red/APIs fuera del monolito `app.py`:
la UI (Streamlit) vive en app.py y llama a funciones puras de aquí.
"""
