# Spark Control · instalación y ampliación

Panel local para CEINPRO que controla aplicaciones y perfiles en ejecución exclusiva. Incluye ComfyUI y el arranque de Qwen3-Coder-Next-FP8 que ya funciona con 65.536 tokens. No descarga modelos, reinstala ComfyUI ni reconstruye la imagen Docker.

## Instalar en el Spark

1. Copia `spark-control.zip` a `/home/ceinpro/Downloads/` y extráelo.
2. Detén los arranques manuales: Ctrl+C en la terminal de ComfyUI; para vLLM, `docker stop vllm_node`. No uses luego `comfy.sh` o `run-recipe.sh` mientras el panel gestione las aplicaciones.
3. Abre una terminal y ejecuta:

```bash
cd /home/ceinpro/Downloads/spark-control
sudo bash install.sh ceinpro
```

El instalador comprueba las carpetas, los ejecutables, los puertos de las aplicaciones y el acceso del usuario a Docker. Si una API sigue respondiendo, se detiene antes de instalar. Si ComfyUI está en otra carpeta, ajusta `catalog.json` antes de instalar. El script original usa rutas relativas; aquí se usan las rutas absolutas conocidas de tu entorno.

Abre **http://192.168.30.70:8090**. La instalación imprime una contraseña aleatoria. También puedes consultarla en el Spark:

```bash
sudo cat /etc/spark-control/panel.token
```

El panel arranca al encender el equipo. Las aplicaciones quedan paradas hasta que elijas un perfil. No se modifica el firewall. El acceso es HTTP con contraseña y está pensado para tu red interna; si lo publicas fuera de ella, coloca un proxy con HTTPS y control de acceso.

## Funcionamiento

- **Activar:** detiene todos los perfiles, espera a systemd y limpia los contenedores declarados. Solo después inicia el perfil seleccionado. Si una parada falla o una API continúa respondiendo, bloquea el cambio.
- **Reiniciar:** realiza la misma secuencia completa.
- **Parar todo:** detiene todas las aplicaciones del catálogo.
- **Verde:** el servicio está activo y su comprobación HTTP responde.
- **Rojo:** parado o error. El error de la operación aparece sobre las tarjetas.
- **Ámbar:** arrancando, comprobando su API o deteniendo. Una API que deja de responder tampoco permanece verde.
- **Registros:** últimas 100 líneas de journald; incluyen la salida del lanzador y sus errores. Los arranques permanecen activos al cerrar el navegador o la terminal.

Cada perfil tiene una unidad de systemd. El controlador usa un bloqueo entre procesos y el panel admite un cambio cada vez. Las unidades también declaran conflictos entre sí. No hay reinicios automáticos de las aplicaciones, por lo que un perfil antiguo no volverá a arrancar durante un cambio.

La exclusividad abarca los perfiles registrados y administrados por este sistema. Los procesos que se lancen manualmente por fuera de él no quedan bajo su control; detecta APIs conocidas que continúan respondiendo y bloquea nuevos arranques. Usa el panel o `sparkctl` para iniciar las aplicaciones.

En ComfyUI, la comprobación confirma que la web responde; no ejecuta una generación. Se aceptan 401/403 para que Usgromana no provoque un falso estado de parada. En vLLM se consulta `/v1/models`. La memoria mostrada es `MemAvailable` de Linux: CPU y GPU comparten memoria en el Spark; no es una medida de la reserva CUDA. La utilización y temperatura proceden de `nvidia-smi` cuando están disponibles.

## Añadir aplicaciones, modelos o variantes de arranque

El catálogo instalado está en `/etc/spark-control/catalog.json`. Cada objeto de `profiles` describe un arranque independiente. Una misma aplicación puede tener varios perfiles, pero solo puede estar activo uno en todo el catálogo.

1. Pulsa **Parar todo** y espera a que termine.
2. Haz una copia y edita el catálogo con permisos de administrador:

```bash
sudo cp /etc/spark-control/catalog.json /etc/spark-control/catalog.json.bak
sudo nano /etc/spark-control/catalog.json
```

3. Añade otro objeto a `profiles`. Por ejemplo, duplica `qwen3-64k` y cambia `id` a `qwen3-16k`, `name` y `description`; en `command`, sustituye el argumento después de `--max-model-len` por `16384`. Conserva `containers: ["vllm_node"]` y la comprobación del puerto 8000.
4. Vuelve a ejecutar `sudo bash install.sh ceinpro` desde esta carpeta. Conserva el catálogo instalado y la contraseña, regenera los conflictos y reinicia el panel. Actualiza la página si es necesario.

Para otro modelo, usa primero un comando de arranque que hayas validado en el Spark y prepara sus pesos e imagen antes de registrarlo. Si cambias el contexto servido, ajusta también los límites del cliente VS Code.

| Campo | Uso |
|---|---|
| `id` | Único; letras minúsculas, números y guiones; máximo 48 caracteres. |
| `app`, `name`, `description` | Identificación y texto que muestra la tarjeta. |
| `cwd` | Directorio absoluto de trabajo. |
| `command` | Lista de programa y argumentos. No es una línea de shell; para un script usa su ruta ejecutable o `/bin/bash` seguido de su ruta. |
| `env` | Variables de entorno para ese arranque. |
| `port` | Puerto del enlace para abrir la aplicación. |
| `health.url` | URL local de comprobación, con `127.0.0.1` o `localhost`. |
| `health.statuses` | Códigos HTTP aceptados; normalmente `[200]`. |
| `health.headers` | Opcional; cabeceras de autenticación para la comprobación. |
| `containers` | Opcional; nombres de contenedores propios que deben detenerse. Nunca incluyas contenedores compartidos con otros servicios. |
| `startup_timeout` | Segundos máximos hasta que la API responda. |
| `tty` | Opcional; `true` proporciona una terminal al lanzador y envía su salida a journald. Activado para la receta actual de vLLM. |
| `detached` | Opcional; solo para lanzadores que terminan con éxito después de dejar la aplicación en segundo plano. Para Docker deben declarar `containers`. Preferible mantener el proceso en primer plano. |

La edición del catálogo es administrativa; el panel no permite introducir comandos arbitrarios. El servidor web y las aplicaciones corren como `ceinpro`. Una utilidad restringida ejecutada mediante sudo gestiona systemd, logs y la parada de los contenedores declarados. El código y catálogo instalados pertenecen a root.

## Diagnóstico

```bash
systemctl status spark-panel.service
systemctl status spark-app@qwen3-64k.service
sudo journalctl -u spark-app@qwen3-64k.service -n 100 --no-pager
sudo sparkctl status
sudo sparkctl start comfyui
sudo sparkctl stop
```

Si reaparece el error de memoria de vLLM, comprueba que no hay otros modelos o procesos ocupándola. Tras detener las aplicaciones, puedes liberar la caché de archivos del sistema como hiciste en la prueba anterior; el panel no lo hace automáticamente:

```bash
sudo sh -c 'sync; echo 3 > /proc/sys/vm/drop_caches'
```

Al eliminar un perfil, detén todo antes de editar. Borra su directorio de conflictos antiguo en `/etc/systemd/system/spark-app@ID.service.d/` y ejecuta de nuevo el instalador. No habilites las unidades de aplicaciones para arrancar al encender el equipo.

Para desactivar el panel manteniendo instalación y configuración:

```bash
sudo sparkctl stop
sudo systemctl disable --now spark-panel.service
```

## Validación del paquete

Pruebas locales del controlador: orden parada/limpieza/arranque; parada fallida; API externa activa; identificador desconocido; limpieza tras un arranque fallido; estados; exclusión entre procesos. Se comprueban también la sintaxis Bash, la compilación Python y la sintaxis JavaScript de la interfaz. El runner de vLLM se prueba con una terminal simulada y un proceso de prueba. No se ha instalado ni ejecutado contra el hardware del Spark desde esta conversación.

La receta existente utiliza `docker exec`, así que los procesos del modelo viven fuera del grupo de procesos del lanzador. Por ese motivo se detiene explícitamente `vllm_node` al finalizar la unidad. Documentación del lanzador: https://github.com/eugr/spark-vllm-docker .
