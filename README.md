# ENID — Cursos de fútbol con pagos por Mercado Pago

Web para vender cursos de fútbol (clases en vivo por Meet + grabación), cobrar con **Mercado Pago (Checkout Pro)** y dar acceso solo a quienes pagaron. Incluye un panel para el dueño (alumnos, accesos, clases, contenido del sitio), mails automáticos y todo lo necesario para publicarla con dominio propio y HTTPS.

| Quiero… | Dónde está |
|---|---|
| Probarla en mi compu con pagos de mentira | [Puesta en marcha](#puesta-en-marcha-10-minutos) y [Probar pagos de mentira](#probar-pagos-de-mentira-con-mercado-pago) |
| Publicarla con dominio y cobrar de verdad | **[docs/ONLINE.md](docs/ONLINE.md)** |
| Configurar los mails y los recordatorios | **[docs/MAILS.md](docs/MAILS.md)** |

## Cómo funciona

1. La persona entra a la web, **crea su cuenta** (o inicia sesión) y elige un curso.
2. **INSCRIBIRME** crea una inscripción *pendiente* y la manda a Mercado Pago.
3. Al pagar, Mercado Pago avisa por **webhook** (firmado) y la web **vuelve a consultar el pago a la API de MP** antes de acreditar. Si el alumno vuelve a la web antes de que llegue el webhook, la vuelta también se confirma contra la API (la URL sola nunca da acceso).
4. La inscripción pasa a *pagada* y en **Mis inscripciones** aparece *Entrar al curso*: la lista de **clases** del curso, las en vivo con su horario (hora de Argentina) y link de Meet y las grabadas con su video.
5. El dueño ve todo en **Alumnos** (`/admin/usuarios`) y puede **dar acceso a mano a quien quiera** (alguien que pagó por PayPal o transferencia, becas, alumnos de antes de la web) y quitárselo cuando quiera.

Un reembolso o contracargo en Mercado Pago revoca el acceso automáticamente. Cada paso importante genera un **mail** (bienvenida, comprobante de pago, acceso dado a mano, recordatorios de clases).

## Puesta en marcha (≈10 minutos)

```bash
python -m venv venv
venv\Scripts\activate            # Windows   (Linux/macOS: source venv/bin/activate)
pip install -r requirements.txt

copy .env.example .env           # (Linux/macOS: cp .env.example .env) y completalo — ver más abajo

flask db upgrade                 # crea las tablas
flask crear-admin                # crea la cuenta del dueño (pide email y contraseña)
flask seed-cursos                # opcional: 3 cursos de ejemplo (después los editás desde el panel)
flask run                        # http://127.0.0.1:5000
```

Variables del `.env` (hay un `.env.example` comentado):

| Variable | Para qué |
|---|---|
| `SECRET_KEY` | Obligatoria. `python -c "import secrets; print(secrets.token_hex(32))"` |
| `MP_ACCESS_TOKEN` | Access Token de Mercado Pago (en el piloto, el de **prueba**) |
| `MP_WEBHOOK_SECRET` | Clave secreta que genera Mercado Pago al configurar el webhook |
| `PUBLIC_URL` | URL pública **https** de la web (ngrok hoy, dominio mañana). A ella vuelve el comprador |
| `MAIL_*` | Opcional. Sin `MAIL_USERNAME`, los mails se imprimen en la consola |

## Probar pagos de mentira con Mercado Pago

1. En [Mercado Pago Developers](https://www.mercadopago.com.ar/developers) → **Tus integraciones** → tu aplicación (Checkout Pro). Con la aplicación se crea una **cuenta de prueba vendedor**; sus credenciales son las de prueba (el Access Token también empieza con `APP_USR-`). Copialo en `MP_ACCESS_TOKEN`.
2. En **Cuentas de prueba** abrí la cuenta **Comprador** (usuario y contraseña). Si al iniciar sesión pide un código por email, está en esa misma tabla.
3. Exponé tu servidor: `ngrok http 5000` y pegá la URL https en `PUBLIC_URL`. Reiniciá `flask run` (el `.env` se lee al arrancar). La cuenta gratuita de ngrok incluye un dominio fijo asignado (dashboard → *Domains*), así que la URL **no cambia** al reiniciar. Eso sí, en el navegador muestra una pantalla de advertencia la primera vez (cookie de 7 días): para probar sobra, para alumnos reales no.
4. **Webhook:** Tus integraciones → tu app → **Webhooks → Configurar notificaciones** → pestaña de **prueba** → URL `https://TU-URL/webhooks/mercadopago` → evento **Pagos** → Guardar. Copiá la **clave secreta** en `MP_WEBHOOK_SECRET` y reiniciá. El botón *Simular* de esa pantalla sirve para ver si llega.
5. Hacé la compra en una **ventana de incógnito**, entrando a Mercado Pago con el usuario **comprador de prueba**. Tarjetas de prueba de Argentina (vencimiento 11/30):

   | Tarjeta | Número | Código |
   |---|---|---|
   | Visa | 4509 9535 6623 3704 | 123 |
   | Mastercard | 5031 7557 3453 0604 | 123 |
   | Mastercard débito | 5287 3383 1025 3304 | 123 |

   El **nombre del titular** define el resultado: `APRO` aprueba el pago; por ejemplo `FUND` simula fondos insuficientes y `SECU` un código de seguridad inválido. La tabla completa (y el documento a cargar) está en la documentación oficial: *Checkout Pro → Integración → Realizar compras de prueba*.

## Checklist del piloto (lo que tiene que andar)

- [ ] Cuenta nueva → compra con `APRO` → vuelve a la web → *Mis inscripciones* dice **Pagada** → *Entrar al curso* muestra Meet y grabación.
- [ ] Compra con `FUND` → queda **Pendiente**, sin acceso → *Completar pago* reintenta sin duplicar filas.
- [ ] Un usuario sin pagar abriendo `/curso/1` es redirigido (sin acceso).
- [ ] Dueño → **Alumnos**: aparece la cuenta con su curso y el total cobrado.
- [ ] Dueño → **Cursos → Clases**: cargá una clase grabada y una en vivo; el alumno con acceso las ve (la próxima destacada), el que no pagó no.
- [ ] Dueño → **Dar acceso a un alumno** con un email nuevo y varios cursos: muestra un enlace para que el alumno elija su contraseña; con ese enlace entra a los cursos. Después, *Alumnos → quitar acceso* se lo saca.
- [ ] Dueño → **Inscripciones → Eliminar** para limpiar las pruebas antes de salir a producción.

## Clases: en vivo y grabadas

Cada curso tiene **varias clases**. Una clase puede ser:

- **En vivo:** fecha y hora (se muestran como *hora de Argentina*, porque hay alumnos en otros países) + link de Meet. Se destaca como *Próxima clase en vivo* y pasa a *En vivo ahora* durante unas 2 horas.
- **Grabada:** link al video (Drive, YouTube no listado…). Si una clase en vivo ya tiene grabación, se muestra el video.
- **Borrador:** desmarcá *Visible para los alumnos* y solo la ves vos hasta que la publiques.

Flujo típico: creás la clase en vivo con su Meet → pasa la clase → la editás y pegás el link de la grabación. Los links tienen que empezar con `http://` o `https://`.

### Profesores

Un profe ve **Panel del profe** (`/profe`) en el menú: ahí están sus cursos y edita su perfil. Puede crear y editar módulos, clases y partes **solo de los cursos que dicta**, y entra a ellos sin pagar. No ve pagos, alumnos ni el resto del panel. Los profes aparecen en la página pública `/profesores`, en la ficha de cada curso y en las tarjetas de la portada.

### Módulos, partes y progreso

- **Módulos:** agrupan clases (*Módulo 1 · Fundamentos tácticos*). Se crean con **Agregar módulo** en las clases del curso, y en cada clase elegís su módulo. Las clases sin módulo aparecen al final como *Otras clases*.
- **Partes:** una clase puede dividirse en varios videos cortos (botón **Partes** de cada clase), como los capítulos de una lista de YouTube. Los links de YouTube, Vimeo y Google Drive (`/file/d/...`) se ven dentro de la web; los demás se abren en otra pestaña.
- **Progreso:** el alumno marca cada parte (o la clase, si no tiene partes) como vista. La web muestra el porcentaje completado de cada clase, de cada módulo y del curso, y un botón *Seguir viendo* que lo lleva a la primera clase sin terminar.

## Panel del dueño

| Ruta | Qué hace |
|---|---|
| `/admin/usuarios` | Todos los usuarios con **fecha de alta y último ingreso**, sus cursos, estado, medio de pago (Mercado Pago, PayPal, transferencia...), fecha y nota; métricas, buscador y **Exportar CSV** |
| `/admin/inscripciones/nueva` | **Dar acceso** a un alumno a uno, varios o todos los cursos, anotando el medio de pago y una nota (crea la cuenta y le manda el mail) |
| `/admin/alumnos/importar` | **Importar alumnos desde un CSV** con vista previa, validación fila por fila y mails de invitación opcionales |
| `/admin/inscripciones` | Todas las inscripciones con su pago; eliminación |
| `/admin/cursos` y `/admin/cursos/<id>/clases` | Cursos (nombre, descripción, precio), sus **módulos** y sus **clases** (en vivo, grabadas o ambas, divididas en partes; borradores; aviso por mail al guardar) |
| `/admin/profesores` | **Profesores:** alta por email (crea la cuenta y da un enlace para elegir contraseña), perfil con foto, cursos que dicta y quitar el rol |
| `/admin/sitio` | **Contenido del sitio:** entrenador, foto de portada, galería de fotos, testimonios, preguntas frecuentes, WhatsApp / Instagram / email, datos legales |
| `/admin/arrepentimientos` | Solicitudes del botón de arrepentimiento |

Notas:
- El botón **Enlace de acceso** (en Alumnos) genera un enlace de 7 días para que un alumno defina o recupere su contraseña.
- Las fotos se achican y se guardan **dentro de la base de datos**: viajan con los backups y no dependen del disco del hosting.
- Las páginas **Términos y condiciones** y **Política de privacidad** son un modelo de partida (con tus datos de titular): hacelas revisar por un profesional antes de cobrar.
- El **botón de arrepentimiento** está en el pie de todas las páginas, sin necesidad de iniciar sesión (Res. 424/2020 de la Secretaría de Comercio Interior). La devolución del dinero se hace desde Mercado Pago; al confirmarse, la web quita el acceso sola.

### Importar alumnos por CSV
En Excel o Google Sheets armá una planilla con las columnas `nombre`, `email`, `cursos` (nombres separados con `|`, o `todos`) y, si querés, `medio` y `nota`; guardala como CSV y subila en **Importar alumnos**. Primero ves una vista previa (cuentas nuevas, accesos nuevos, errores por fila) y recién al confirmar se guarda. Importar el mismo archivo dos veces no duplica nada. Hay una plantilla de ejemplo para descargar en esa pantalla.

## Comandos útiles

| Comando | Para qué |
|---|---|
| `flask db upgrade` | Crea o actualiza las tablas (correrlo después de cada actualización) |
| `flask crear-admin` | Crea (o promueve) un administrador |
| `flask seed-cursos` | Carga cursos y clases de ejemplo |
| `flask verificar-config` | Revisa que la configuración esté lista para cobrar de verdad |
| `flask probar-mail tu@correo.com` | Prueba el envío de mails y muestra el error exacto si falla |
| `flask enviar-recordatorios [--dry-run]` | Recordatorios de clases en vivo (programarlo cada 10 minutos) |
| `herramientas/backup.sh` | Copia de seguridad comprimida de la base |

## Poner online

La guía paso a paso está en **[docs/ONLINE.md](docs/ONLINE.md)**: servidor propio con `docker compose up` (HTTPS automático con Caddy, PostgreSQL, recordatorios y backups) o un hosting con `Dockerfile`, más el pase de Mercado Pago a producción y un checklist de salida.

En resumen: en producción usá credenciales productivas de Mercado Pago, `PUBLIC_URL` con tu dominio https, PostgreSQL (no SQLite en un disco efímero), mails SMTP configurados y `flask verificar-config` sin errores. Rotá `SECRET_KEY`, el Access Token y la clave del webhook si alguna vez estuvieron en un repositorio o en un zip compartido.

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests
```

Cubren el circuito completo con Mercado Pago simulado (registro → compra → webhook firmado → acceso, firma inválida, monto alterado, rechazos, reembolsos, retorno sin webhook), clases, dar y quitar acceso, importación CSV, mails y recordatorios (sin duplicados), subida y optimización de fotos, testimonios, páginas legales, arrepentimiento, cabeceras de seguridad, límite de intentos y verificación de configuración. Para correrlos contra PostgreSQL: `TEST_DATABASE_URL=postgresql://usuario:clave@localhost/base_de_prueba pytest tests`. `herramientas/probar_webhook.py` manda un webhook firmado a tu servidor local.

## Estructura

```
app.py            compra, pagos y webhook, cuentas, panel de alumnos/cursos/clases, seguridad, errores
sitio.py          contenido del sitio (fotos, testimonios, preguntas, ajustes), legales, arrepentimiento, /salud
gestion.py        Mi cuenta, baja de avisos, importación CSV, tarea de recordatorios, comandos de consola
emailer.py        envío de mails (SMTP), enlaces firmados, mensajes
avisos.py         recordatorios y avisos de clases (sin duplicados)
importador.py     lectura y validación del CSV de alumnos
imagenes.py       validación y optimización de fotos
models.py         Usuario, Curso, Clase, Inscripcion, Pago, Imagen, Foto, Testimonio, ...
forms.py          formularios WTForms
migrations/       Alembic (flask db upgrade)
templates/        Jinja2 (admin/ panel, emails/, legal/, errores/)
static/           estilos, Bootstrap y fuentes alojados en el propio sitio (sin CDN)
Dockerfile, docker-compose.yml, Caddyfile, docker/    publicación con HTTPS automático
herramientas/     backup.sh y utilidades manuales
docs/             ONLINE.md (publicar) y MAILS.md (mails y recordatorios)
tests/            pytest
```
