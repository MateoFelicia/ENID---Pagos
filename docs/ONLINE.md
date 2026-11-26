# Poner ENID online (con dominio, HTTPS y pagos reales)

Esta guía te lleva del piloto a una web pública que cobra de verdad. Hay dos caminos; el A es el recomendado.

| | A. Servidor propio (VPS) + Docker | B. Hosting tipo PaaS (Render, Railway, Fly...) |
|---|---|---|
| Qué hacés | Alquilás un servidor chico y corrés `docker compose up` | Conectás el repositorio y el servicio construye el `Dockerfile` |
| HTTPS | Automático (Caddy) | Lo da el hosting |
| Base de datos | PostgreSQL en el mismo servidor | PostgreSQL gestionado del hosting |
| Recordatorios | Incluidos (servicio `recordatorios`) | Cron del hosting o servicio externo |
| Ideal para | Control total y un solo gasto mensual | No querer administrar un servidor |

> **No uses ngrok ni un plan gratuito que se duerme.** En el plan gratuito de Render, por ejemplo, el servicio se duerme tras 15 minutos sin visitas y el disco es efímero: una base SQLite ahí se pierde. Para cobrar necesitás un servicio que esté siempre encendido y una base persistente.

---

## Camino A: VPS + Docker Compose

### 1. Dominio y servidor
1. Registrá un dominio (para `.com.ar`, en NIC Argentina; para otros, en cualquier registrador).
2. Alquilá un VPS Linux (Ubuntu 24.04 sirve; 1–2 GB de RAM alcanzan para empezar) y anotá su IP pública.
3. En el panel DNS del dominio creá un **registro A**: `cursos` → IP del servidor (o `@` si querés el dominio raíz). Puede tardar un rato en propagarse.

### 2. Preparar el servidor
```bash
# Conectado por SSH al servidor
curl -fsSL https://get.docker.com | sh          # instala Docker y Docker Compose
sudo ufw allow 22 && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw enable
```

### 3. Subir y configurar ENID
```bash
git clone <tu-repositorio> enid && cd enid       # o copiá la carpeta con scp
cp .env.produccion.example .env
nano .env                                        # completá DOMINIO, PUBLIC_URL, SECRET_KEY, POSTGRES_PASSWORD, MP_*, MAIL_*
docker compose up -d --build
docker compose logs -f web                       # tiene que terminar en "Booting worker"
```
Caddy pide solo el certificado HTTPS cuando el dominio ya apunta al servidor. Entrá a `https://tu-dominio`.

### 4. Primeros pasos
```bash
docker compose exec web flask crear-admin        # tu usuario de dueño
docker compose exec web flask probar-mail tu@correo.com
docker compose exec web flask verificar-config   # tiene que dar 0 errores
```
Lo mismo se ve desde la web en **Administración → ¿Lista para abrir?**, junto con lo que se revisa a mano.
Después, desde la web: **Administración → Cursos y clases** (cargá los cursos reales) y **Contenido del sitio** (entrenador, fotos, testimonios, datos legales).

### 5. Mantenimiento
- **Actualizar:** `git pull && docker compose up -d --build` (las migraciones corren solas).
- **Backups diarios:** `crontab -e` y agregá `0 4 * * * cd /ruta/a/enid && herramientas/backup.sh /ruta/backups 14`. Copiá la carpeta de backups a otro lugar (tu computadora, un bucket): una copia en el mismo servidor no te salva si el servidor se pierde.
- **Restaurar:** `gunzip -c backups/enid-AAAAMMDD-HHMMSS.sql.gz | docker compose exec -T db psql -U enid enid` (sobre una base vacía). Probalo una vez antes de necesitarlo.
- **Monitoreo:** registrá `https://tu-dominio/salud` en un servicio de monitoreo gratuito (UptimeRobot o similar): responde 200 si la web y la base andan.
- **Logs:** `docker compose logs -f web`.
- **Google:** registrá el dominio en Google Search Console y cargá `https://tu-dominio/sitemap.xml` (lista las páginas públicas y las noticias; también figura en `robots.txt`).

---

## Camino B: hosting con Dockerfile (Render, Railway, Fly.io...)
1. Creá un servicio **Web** desde tu repositorio; el hosting detecta el `Dockerfile`.
2. Creá una base **PostgreSQL** del mismo hosting y copiá su URL en la variable `DATABASE_URL`.
3. Cargá las variables de `.env.produccion.example` (sin `DOMINIO` ni `POSTGRES_PASSWORD`). `PUBLIC_URL` es la URL final con tu dominio.
4. Agregá tu dominio personalizado en el panel del hosting y creá el registro DNS que te indique.
5. Corré `flask crear-admin` desde la consola del servicio.
6. **Recordatorios de clases**, a elegir:
   - un *Cron Job* del hosting que ejecute `flask enviar-recordatorios` cada 10 minutos (y `flask sincronizar-membresias` una vez por día, si usás la membresía), o
   - un servicio de cron externo que llame a `POST https://tu-dominio/tareas/recordatorios` con la cabecera `Authorization: Bearer <CRON_TOKEN>` (definí `CRON_TOKEN` en las variables).
7. Los backups dependen del hosting: activá los de la base de datos.

---

## Mercado Pago: pasar a producción
Según la documentación oficial de Checkout Pro:

1. En **Tus integraciones**, abrí tu aplicación → **Credenciales de producción** → **Activar credenciales**. Te pide el rubro, la **URL de tu sitio web** (tu dominio https) y aceptar los términos.
2. Copiá el **Access Token de producción** en `MP_ACCESS_TOKEN` (reemplaza al de prueba).
3. En **Webhooks → Configurar notificaciones**, en la pestaña **de producción**, poné `https://tu-dominio/webhooks/mercadopago`, marcá los eventos **Pagos** y **Planes y suscripciones** (para la membresía mensual) y guardá. Copiá la **clave secreta** en `MP_WEBHOOK_SECRET`.
4. Reiniciá (`docker compose up -d`) y corré `flask verificar-config`.
5. **En producción Mercado Pago exige certificado SSL**: con HTTPS ya lo cumplís.
6. Opcional pero recomendable: en el panel de Mercado Pago, la herramienta **Medir la calidad de la integración**: le pasás el ID de un pago real y te indica qué mejorar.

### Primera compra real
Antes de abrir al público, comprá vos un curso con una tarjeta propia (podés crear uno barato, solo para esta prueba) y verificá: se acredita el pago, llega el mail de confirmación, aparece el curso en *Mis cursos* y el pago figura en **Alumnos**. Después pedí el reembolso desde Mercado Pago y comprobá que la web le quita el acceso sola. Eliminá el curso de prueba al terminar.

---

## Checklist de salida
- [ ] `flask verificar-config` sin errores.
- [ ] La web abre por `https://` y el candado está bien (sin avisos).
- [ ] **Datos del titular** completos (Contenido del sitio → Datos legales) y **términos y política de privacidad revisados por un abogado**: los textos incluidos son un modelo de partida, no asesoramiento legal.
- [ ] El **botón de arrepentimiento** está visible en el pie de todas las páginas, y sabés cómo responder a una solicitud (Administración → Arrepentimientos, y el reembolso se hace en Mercado Pago).
- [ ] `flask probar-mail` llega a tu bandeja de entrada (no a spam).
- [ ] Un recordatorio de clase llega (`flask enviar-recordatorios --dry-run` muestra a quién).
- [ ] Backup programado **y restauración probada**.
- [ ] Monitoreo de `/salud` activo.
- [ ] Hablaste con tu contador sobre inscripción y facturación (ARCA, ex AFIP) y sobre el IVA o monotributo que corresponda a la venta de cursos.
- [ ] Eliminaste las inscripciones y usuarios de prueba.
