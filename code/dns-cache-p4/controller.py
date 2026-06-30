#!/usr/bin/env python3
"""
controller.py

Este controlador:
- Instala reglas de forwarding en s1.
- Carga entradas iniciales en los registers de caché DNS.
- Lee contadores de hits y misses.
- Puede correr en modo "updater": escucha respuestas DNS reales
- que pasan por la red y actualiza el caché del switch en tiempo real.
"""

import argparse
import struct
import subprocess
import sys
import threading
import time


# Configuración de switches y rutas

SWITCHES = {
    "s1": 9090,
}

ROUTES = {
    "s1": [
        ("10.0.1.1",   32, "08:00:00:00:01:11", "08:00:00:00:01:00", 1),
        ("10.0.1.2",   32, "08:00:00:00:01:22", "08:00:00:00:01:00", 2),
        ("10.0.1.3",   32, "08:00:00:00:01:33", "08:00:00:00:01:00", 3),
        ("10.0.1.4",   32, "08:00:00:00:01:44", "08:00:00:00:01:00", 4),
        ("10.0.1.100", 32, "08:00:00:00:01:99", "08:00:00:00:01:00", 5),
    ],
}

# Entradas preconfiguradas en el caché al iniciar.
#
# El índice se calcula igual que en el P4:
#   index = primeros_4_bytes_del_nombre_dns & 0x3ff
#
# IP en decimal:
#   10.10.10.10 = 168430090
#   10.20.20.20 = 169088020
#   10.30.30.30 = 169745950
CACHE_ENTRIES = [
    {
        "domain":     "example.com",
        "index":      97,
        "ip":         "10.10.10.10",
        "ip_decimal": 168430090,
    },
    {
        "domain":     "ucr.ac.cr",
        "index":      882,
        "ip":         "10.20.20.20",
        "ip_decimal": 169088020,
    },
    {
        "domain":     "cache.test",
        "index":      355,
        "ip":         "10.30.30.30",
        "ip_decimal": 169745950,
    },
]


# Funciones de índice: replicar la lógica del P4

CACHE_MASK = 0x3FF  # 1024 entradas

def _dns_wire_key(qname: str) -> int:
    """
    Devuelve los primeros 4 bytes del nombre DNS codificado en wire format.
    Replicando exactamente lo que hace el parser de router.p4 al extraer
    el header dns_name_key_t.
    """
    parts = qname.rstrip(".").split(".")
    wire = b""
    for part in parts:
        wire += bytes([len(part)]) + part.encode()
    wire += b"\x00"

    if len(wire) < 4:
        return 0

    return struct.unpack("!I", wire[:4])[0]


def cache_index_for(qname: str) -> int:
    """Índice de caché para un nombre de dominio dado."""
    return _dns_wire_key(qname) & CACHE_MASK


def ip_to_decimal(ip: str) -> int:
    """Convierte una IP en notación decimal (ej. '10.0.0.1') a entero."""
    parts = ip.split(".")
    result = 0
    for part in parts:
        result = (result << 8) | int(part)
    return result


# Interfaz con simple_switch_CLI vía Thrift

def _cli(thrift_port: int, commands: list) -> str:
    """
    Envía una lista de comandos al simple_switch_CLI del switch indicado
    y devuelve la salida combinada.
    """
    cmd_str = "\n".join(commands) + "\n"

    result = subprocess.run(
        ["simple_switch_CLI", "--thrift-port", str(thrift_port)],
        input=cmd_str,
        capture_output=True,
        text=True,
        timeout=10,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)

    output = result.stdout + result.stderr
    errors = [line for line in output.splitlines() if "Error" in line]

    if errors:
        raise RuntimeError("\n".join(errors))

    return output


def mac_to_hex(mac: str) -> str:
    return "0x" + mac.replace(":", "")


# Comandos de configuración

def build_forwarding_commands(switch_name: str) -> list:
    commands = ["table_clear MyIngress.ipv4_lpm"]

    for prefix, length, dst_mac, src_mac, port in ROUTES[switch_name]:
        commands.append(
            "table_add MyIngress.ipv4_lpm MyIngress.ipv4_forward "
            f"{prefix}/{length} => {mac_to_hex(dst_mac)} {mac_to_hex(src_mac)} {port}"
        )

    return commands


def build_cache_commands() -> list:
    commands = []

    for entry in CACHE_ENTRIES:
        commands.append(
            f"register_write MyIngress.cache_valid {entry['index']} 1"
        )
        commands.append(
            f"register_write MyIngress.cache_ip {entry['index']} {entry['ip_decimal']}"
        )

    return commands


def build_counter_commands() -> list:
    return [
        "counter_read MyIngress.dns_query_counter 0",
        "counter_read MyIngress.dns_response_counter 0",
        "counter_read MyIngress.dns_hit_counter 0",
        "counter_read MyIngress.dns_miss_counter 0",
    ]


def write_cache_entry(thrift_port: int, domain: str, ip: str):
    """
    Escribe una entrada en el caché del switch P4.
    Se llama cuando el updater detecta una respuesta DNS nueva.
    """
    index = cache_index_for(domain)
    ip_dec = ip_to_decimal(ip)

    commands = [
        f"register_write MyIngress.cache_valid {index} 1",
        f"register_write MyIngress.cache_ip {index} {ip_dec}",
    ]

    _cli(thrift_port, commands)


# Configuración inicial del switch

def configure_switch(switch_name: str, thrift_port: int, load_cache: bool = True):
    commands = build_forwarding_commands(switch_name)

    if load_cache:
        commands += build_cache_commands()

    _cli(thrift_port, commands)

    print(
        f"{switch_name}: {len(ROUTES[switch_name])} reglas de forwarding instaladas "
        f"en thrift port {thrift_port}."
    )

    if load_cache:
        print("Entradas iniciales de caché cargadas:")
        for entry in CACHE_ENTRIES:
            print(
                f"  {entry['domain']} -> {entry['ip']} "
                f"(index={entry['index']})"
            )


def configure_all(switch: str = "all", load_cache: bool = True):
    time.sleep(1)

    selected = SWITCHES.keys() if switch == "all" else [switch]

    for sw in selected:
        if sw not in SWITCHES:
            raise ValueError(f"Switch desconocido: {sw}")

        configure_switch(sw, SWITCHES[sw], load_cache=load_cache)


# Lectura de contadores

def show_counters(switch: str = "s1"):
    if switch not in SWITCHES:
        raise ValueError(f"Switch desconocido: {switch}")

    output = _cli(SWITCHES[switch], build_counter_commands())
    print(output)


# Updater dinámico: escucha respuestas DNS y actualiza el caché en vivo

def _parse_dns_response(pkt):
    """
    Recibe un paquete Scapy con una respuesta DNS.
    Se extraen los registros tipo A y actualiza el caché del switch.
    """
    # Importamos acá para que el módulo funcione sin scapy si no se usa --watch
    from scapy.layers.dns import DNS, DNSRR
    from scapy.layers.inet import UDP

    if not pkt.haslayer(DNS):
        return

    dns = pkt[DNS]
    if dns.qr != 1 or dns.ancount == 0:
        return

    thrift_port = SWITCHES["s1"]
    answer = dns.an

    while answer is not None:
        #Solo procesamos registros tipo A (IPv4)
        if answer.type == 1 and hasattr(answer, "rdata"):
            qname = answer.rrname.decode().rstrip(".")
            ip = answer.rdata
            # Verificar que la IP tenga formato válido antes de escribir
            parts = ip.split(".")
            if len(parts) != 4:
                answer = answer.payload if hasattr(answer, "payload") else None
                continue

            index = cache_index_for(qname)
            try:
                write_cache_entry(thrift_port, qname, ip)
                print(f"[updater] caché actualizado: {qname} -> {ip} (index={index})")
            except Exception as exc:
                print(f"[updater] error al escribir {qname}: {exc}", file=sys.stderr)

        answer = answer.payload if hasattr(answer, "payload") else None
        try:
            from scapy.layers.dns import DNSRR
            if not isinstance(answer, DNSRR):
                break
        except Exception:
            break


def run_updater(iface: str = "s1-eth5", log_file: str = None):
    """
    Escucha en la interfaz debida y actualiza el caché del switch cuando llega una respuesta DNS nueva.
    Si se da log_file, además de imprimir a stdout escribe ahí la línea de
    "escuchando" topology.py usa eso para saber cuándo el socket raw de
    Scapy ya está abierto, en vez de adivinar con un sleep fijo.
    """
    from scapy.all import sniff

    ready_msg = f"[updater] escuchando respuestas DNS en {iface} ...\n"
    print(ready_msg, end="")
    print("[updater] presiona Ctrl+C para detener.\n")

    if log_file:
        try:
            with open(log_file, "a") as f:
                f.write(ready_msg)
        except OSError:
            pass

    try:
        sniff(
            iface=iface,
            filter="udp src port 53",
            prn=_parse_dns_response,
            store=False,
        )
    except KeyboardInterrupt:
        print("\n[updater] detenido.")


def run_updater_background(iface: str = "s1-eth5",
                            log_file: str = "/tmp/dns_updater.log") -> threading.Thread:
    """
    Igual que run_updater pero en un hilo de fondo.
    Verifica que scapy esté disponible antes de arrancar el hilo para dar
    un error claro en vez de fallar silenciosamente dentro del thread.
    """
    try:
        import scapy 
    except ImportError:
        print(
            "Error: scapy no está disponible para este intérprete de Python.\n"
            "Si usas un virtualenv, asegúrate de correr con sudo -E python3.\n"
            "O instala scapy con: pip3 install scapy --break-system-packages",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        open(log_file, "w").close()
    except OSError:
        pass

    t = threading.Thread(target=run_updater, args=(iface, log_file), daemon=True)
    t.start()
    return t


# Punto de entrada

def main():
    parser = argparse.ArgumentParser(
        description="Controlador para Proyecto A: Caché DNS en P4"
    )

    parser.add_argument(
        "--switch",
        choices=["all", "s1"],
        default="all",
        help="Switch a configurar. Default: all",
    )

    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Instala solo forwarding, sin cargar entradas iniciales de caché.",
    )

    parser.add_argument(
        "--counters",
        action="store_true",
        help="Lee y muestra los contadores DNS/hit/miss del switch.",
    )

    parser.add_argument(
        "--watch",
        action="store_true",
        help=(
            "Modo updater: escucha respuestas DNS reales y actualiza el caché "
            "del switch en tiempo real. Requiere ejecutar como root."
        ),
    )

    parser.add_argument(
        "--iface",
        default="s1-eth5",
        help="Interfaz a escuchar en modo --watch. Default: s1-eth5",
    )

    args = parser.parse_args()

    try:
        if args.counters:
            show_counters("s1")

        elif args.watch:
            # Primero instalamos forwarding (sin caché) y luego nos quedamos
            # escuchando para ir aprendiendo dominios sobre la marcha.
            configure_all(args.switch, load_cache=False)
            print()
            run_updater(iface=args.iface)

        else:
            configure_all(args.switch, load_cache=not args.no_cache)

    except Exception as exc:
        print(f"Error en controller.py: {exc}", file=sys.stderr)
        print(
            "Verifique que la topología esté corriendo con: sudo python3 topology.py",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
