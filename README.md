# ENID - Sistema de Inscripciones y Pagos

Aplicación web para la gestión de cursos, inscripciones y pagos de la Escuela de Formación Futbolística ENID, con integración de Mercado Pago (Checkout Pro).

## Características

- **Landing page** responsive con Bootstrap 5 (mobile-first)
- **Catálogo de cursos** públicos con precios
- **Inscripción a cursos** con creación de preferencia de pago en Mercado Pago
- **Webhook de Mercado Pago** para confirmación automática de pagos
- **Sistema de usuarios**: registro, inicio/cierre de sesión, contraseñas hasheadas (bcrypt)
- **Panel de administración** (solo admins):
  - Gestión de cursos (crear, editar, desactivar)
  - Listado de inscripciones con estado de pago
- **Base de datos** SQLite con migraciones (Alembic/Flask-Migrate)

## Tecnologías

| Capa | Tecnología |
|------|------------|
| Backend | Flask 3, Python 3.11+ |
| Base de datos | SQLAlchemy 2 + SQLite |
| Migraciones | Flask-Migrate / Alembic |
| Autenticación | Flask-Login |
| Formularios | Flask-WTF + WTForms |
| Pagos | Mercado Pago SDK (Checkout Pro) |
| Frontend | Bootstrap 5.3, plantillas Jinja2 |
| Entorno | python-dotenv, virtualenv |

## Estructura del proyecto

```
appPagos/
├── app.py              # Aplicación principal (rutas, webhook, config)
├── models.py           # Modelos: Usuario, Curso, Inscripcion, Pago
├── forms.py            # Formularios WTForms
├── db.py               # Instancia SQLAlchemy
├── requirements.txt    # Dependencias
├── .env                # Variables de entorno (no versionar)
├── migrations/         # Migraciones Alembic
├── templates/
│   ├── base.html       # Layout principal + navbar
│   ├── index.html      # Landing + formulario inscripción
│   ├── registro.html
│   ├── iniciar_sesion.html
│   ├── mis_inscripciones.html
│   └── admin/
│       ├── cursos.html
│       ├── curso_form.html
│       └── inscripciones.html
└── static/
    └── css/estilos.css
```

## Configuración

### 1. Clonar y crear entorno virtual

```bash
cd appPagos
python -m venv venv
venv\Scripts\activate      # Windows
# source venv/bin/activate  # Linux/macOS
```

### 2. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 3. Variables de entorno (`.env`)

Crea un archivo `.env` en la raíz del proyecto:

```env
SECRET_KEY=tu-clave-secreta-larga-y-aleatoria
MP_ACCESS_TOKEN=APP_USR-xxxxxxxxxxxxxxxxxxxxxxxx
MP_WEBHOOK_SECRET=whsec_xxxxxxxxxxxxxxxxxxxxxxxx
```

- `SECRET_KEY`: cualquier string largo y aleatorio (usar `python -c "import secrets; print(secrets.token_hex(32))"`)
- `MP_ACCESS_TOKEN`: Access Token de tu aplicación de Mercado Pago (producción o test)
- `MP_WEBHOOK_SECRET`: Clave secreta del webhook (se obtiene al configurar el webhook en el panel de Mercado Pago)

### 4. Inicializar base de datos

```bash
flask db upgrade
```

Esto creará las tablas `cursos`, `inscripciones`, `pagos`, `usuarios` y aplicará las migraciones de usuario y rol admin.

### 5. (Opcional) Crear usuario administrador

```bash
flask shell
>>> from app import app, db
>>> from models import Usuario
>>> with app.app_context():
...     u = Usuario(nombre="Admin", email="admin@enid.com")
...     u.establecer_password("tu-password")
...     u.es_admin = True
...     db.session.add(u)
...     db.session.commit()
```

### 6. Ejecutar en desarrollo

```bash
flask run
# o: python app.py
```

La app estará en `http://127.0.0.1:5000`.

## Webhook de Mercado Pago (producción)

Para que los pagos se confirmen automáticamente:

1. En el panel de Mercado Pago > Tu aplicación > Webhooks
2. Agregar URL: `https://TU_DOMINIO/webhooks/mercadopago`
3. Seleccionar evento: `payment`
4. Copiar la **clave secreta** al `.env` como `MP_WEBHOOK_SECRET`

**Importante**: En desarrollo local usa [ngrok](https://ngrok.com/) para exponer tu puerto 5000:

```bash
ngrok http 5000
# Usa la URL https que te dé ngrok como webhook URL
```

## Flujo de pago

1. Usuario elige curso en la landing → clic "INSCRIBIRME"
2. Completa nombre (y email si no está logueado) → envía formulario
3. Se crea `Inscripcion` (estado=pendiente) + `Pago` (estado=pendiente)
4. Se crea preferencia en Mercado Pago → redirige a Checkout Pro
5. Usuario paga → Mercado Pago envía webhook a `/webhooks/mercadopago`
6. Webhook valida firma, consulta el pago, actualiza `Pago.estado` e `Inscripcion.estado`

## Comandos útiles

```bash
# Crear migración tras cambios en models.py
flask db migrate -m "descripcion del cambio"

# Aplicar migraciones
flask db upgrade

# Ver migraciones pendientes
flask db history

# Ejecutar tests (si existen)
pytest
```

## Notas de seguridad

- Nunca commitees el archivo `.env` ni la base de datos `pagos.db`
- Usa credenciales de **producción** solo en entorno real con HTTPS
- El webhook valida firma HMAC (`x-signature`, `x-request-id`) antes de procesar
- Las contraseñas se almacenan como hash bcrypt (`werkzeug.security`)

## Licencia

Uso interno - ENID Formación Futbolística