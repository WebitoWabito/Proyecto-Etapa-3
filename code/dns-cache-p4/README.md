# Proyecto A — Caché DNS en el Data Plane (P4)

Implementación de un caché DNS directamente en el plano de datos usando P4 sobre BMv2/Mininet. El switch intercepta consultas DNS, responde directamente cuando el dominio está en caché (HIT) y reenvía al servidor DNS real cuando no lo está (MISS). Un controlador Python actualiza el caché en tiempo real al aprender respuestas nuevas.

---

## Requisitos

- Python 3.10+
- p4c (compilador P4 para BMv2)
- BMv2 simple_switch
- Mininet
- Scapy (`pip install scapy`)
- dig (`apt install dnsutils`)


---

## Estructura del proyecto

```
dns-cache-p4/
    router.p4           # Código P4: parser, caché, lógica HIT/MISS
    controller.py       # Controlador: forwarding, caché inicial, updater dinámico
    topology.py         # Topología Mininet con el switch P4
    dns_server.py       # Servidor DNS simulado con Scapy
    test_router.py      # Pruebas de conectividad básica
    test_dns_cache.py   # Pruebas HIT y MISS del caché
    test_latency.py     # Benchmark de latencia HIT vs MISS
    Makefile
build/              # Artefactos de compilación (generados por make)
```

---

## Compilar

```bash
make
```

Esto genera `build/router.json` y `router.p4info.txtpb`. Solo es necesario compilar de nuevo si se modifica `router.p4`.

---

## Ejecución DE pruebas automáticas

### 1. Levantar la topología

En una terminal desde el directorio /dns-cache-p4:


Prueba de conectividad y DNS HIT desde caché P4, se genera la tabla y se guardan los datos en un .txt: 
```bash
sudo -E python3 topology.py --auto-test
cat /tmp/latency_results.txt
```

Prueba de DNS MISS sin servidor y con servidor, se genera la tabla y se guardan los datos en un .txt: 
```bash
sudo -E python3 topology.py --miss-test
cat /tmp/latency_results_miss.txt
```

Se actualiza el caché y se hace la prueba DNS HIT desde caché p4, se genera la tabla y se guardan los datos en un .txt: 
```bash
sudo -E python3 topology.py --watch-test
cat /tmp/latency_results_watch.txt
```

---


## Descripción del diseño P4

### Parser

El parser sigue la cadena: Ethernet → IPv4 → UDP → DNS. Si el puerto UDP destino es 53 y el bit `qr=0` (consulta), extrae los primeros 4 bytes del nombre DNS codificado (`dns_name_key_t`). Según esos bytes identifica el dominio y parsea el resto de la pregunta para poder construir una respuesta válida.

### Lógica HIT/MISS

El índice de caché se calcula como:

```
index = primeros_4_bytes_nombre_dns & 0x3ff
```

Esto da 1024 posibles entradas (el tamaño de los registers). Si `cache_valid[index] == 1`, el switch construye y envía la respuesta DNS directamente al cliente invirtiendo las direcciones IP/MAC/UDP y agregando el header Answer. Si no, el paquete sigue el forwarding normal hacia el servidor DNS real.


### Contadores

Hay 4 contadores de paquetes: `dns_query_counter`, `dns_response_counter`, `dns_hit_counter`, `dns_miss_counter`. Se Pueden leer con `python3 controller.py --counters`.


---

## Uso de IA

Algunas partes del código fueron generadas con asistencia de IA. Específicamente, el updater dinámico en `controller.py`, el script de benchmark `test_latency.py`, el modo `--watch-test` en `topology.py` y algunas partes de los prints como lo son los benchmarks por ejemplo. Estas partes fueron revisadas y comprendidas por nosotros.
