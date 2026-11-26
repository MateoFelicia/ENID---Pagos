# Mails de ENID

## Qué mails envía la web
| Mail | Cuándo | ¿Se puede dar de baja? |
|---|---|---|
| Bienvenida | Al crear la cuenta | No (es de cuenta) |
| Recuperar contraseña | Al pedirlo | No |
| Acceso a cursos | Cuando el dueño da acceso a mano o importa alumnos (trae el enlace para elegir contraseña, vale 7 días) | No |
| Comprobante de pago | Cuando se acredita un pago en Mercado Pago (una sola vez) | No |
| Recordatorio de clase en vivo | 24 h y 1 h antes | **Sí** |
| Clase nueva / ya está la grabación | Cuando el dueño tilda «Avisar por mail» al guardar una clase | **Sí** |
| Arrepentimiento | Constancia para quien lo pidió y aviso para el dueño | No |
| Confirmar suscripción al newsletter | Cuando alguien se anota a las novedades (doble confirmación) | No hace falta: sin confirmar no recibe nada |
| Noticia | Cuando el dueño toca «Mandar por mail» en Administración → Noticias (una sola vez por noticia) | **Sí** (enlace al pie, botón de baja) |

La baja de avisos se hace desde **Mi cuenta** o con el enlace al pie de cada mail (sin iniciar sesión).

## Configurar el envío (SMTP)
Sin `MAIL_USERNAME`, los mails **no se envían**: se imprimen en la consola (sirve para desarrollar). Para enviar de verdad completá en el `.env`:

```
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USERNAME=tu-cuenta@gmail.com
MAIL_PASSWORD=<contraseña de aplicación>
MAIL_DEFAULT_SENDER=ENID <tu-cuenta@gmail.com>
CONTACT_EMAIL=el-mail-donde-te-escriben@...      # opcional: «responder a» de los mails y destino de los avisos para vos
```

### Opción 1: Gmail (para empezar)
1. Activá la **verificación en 2 pasos** en la cuenta de Google.
2. En la cuenta de Google, buscá **Contraseñas de aplicaciones**, creá una para «ENID» y usá esa clave de 16 letras como `MAIL_PASSWORD` (no tu contraseña normal).
3. Gmail tiene un tope diario de envíos (revisalo en la ayuda de Google): alcanza para una escuela chica, pero no para campañas.

### Opción 2: servicio de mails con tu dominio (recomendado al crecer)
Servicios como Brevo, Resend, Mailgun o Amazon SES ofrecen SMTP: te dan servidor, puerto, usuario y clave para pegar en el `.env`. Para que los mails lleguen a la bandeja de entrada y no a spam, verificá tu dominio con los registros DNS que te pide el servicio:
- **SPF** y **DKIM** (los da el servicio; son obligatorios en la práctica).
- **DMARC** (recomendado): un registro TXT `_dmarc` con una política inicial `v=DMARC1; p=none; rua=mailto:tu@correo` y, cuando todo funcione, endurecerla.
- Usá un remitente de tu dominio (`avisos@tudominio.com.ar`) en `MAIL_DEFAULT_SENDER`.

### Mail de empresa (para recibir y responder)
El envío automático (SMTP) y la casilla donde leés y contestás son dos cosas distintas:

| Para qué | Opción recomendada | Costo |
|---|---|---|
| Casilla `contacto@tudominio.com.ar` para leer y responder | Zoho Mail (plan gratis para pocos usuarios) o Google Workspace | Gratis / pago mensual por usuario |
| Mails automáticos de la web y newsletter | Brevo (plan gratis: 300 mails por día) u otro servicio SMTP | Gratis para empezar |

Los dos se configuran con registros DNS del dominio (MX para recibir; SPF, DKIM y DMARC para enviar). Pegá en `CONTACT_EMAIL` la casilla de empresa: es el «responder a» de todos los mails.

> El newsletter sale con la misma configuración SMTP. Con Gmail funciona para pocos suscriptores, pero tiene tope diario y más chances de ir a spam. La página **Administración → ¿Lista para abrir?** te avisa.

## Probar
```bash
flask probar-mail tu@correo.com
# con Docker:  docker compose exec web flask probar-mail tu@correo.com
```
Muestra el servidor y el usuario que usa y, si algo falla (clave, puerto, remitente), el error exacto. Si el servidor SMTP no responde, a los 20 segundos informa el error (`MAIL_TIMEOUT` lo cambia).

## Recordatorios de clases en vivo
`flask enviar-recordatorios` busca las clases en vivo de las próximas 24 horas y avisa a los alumnos con acceso que no se dieron de baja: una vez entre 24 y 12 horas antes y otra en la última hora. Cada aviso queda registrado, así que **se puede ejecutar cada 10 minutos sin duplicar nada**.

- `flask enviar-recordatorios --dry-run` muestra a quién le llegaría, sin enviar.
- **Docker Compose:** ya viene incluido (servicio `recordatorios`).
- **Servidor sin Docker:** `crontab -e` → `*/10 * * * * cd /ruta/enid && venv/bin/flask enviar-recordatorios`.
- **Hosting sin cron:** definí `CRON_TOKEN` y llamá cada 10 minutos desde un servicio de cron externo: `POST https://tu-dominio/tareas/recordatorios` con la cabecera `Authorization: Bearer <CRON_TOKEN>`.

> Solo reciben recordatorio las clases **publicadas**, **con fecha y link de Meet** y **sin grabación**. Los horarios se muestran siempre en hora de Argentina.

## Depurar
`EMAIL_ASYNC=0` en el `.env` hace que los mails se envíen en el momento (en vez de en segundo plano) y los errores aparezcan en el log.
