#!/usr/bin/env python3
"""
topology.py 

Topología:
    h1
    h2
        sw1  ---  dns
    h3 
    h4 

- h1-h4 son clientes DNS.
- sw1 es el switch P4 ejecutando BMv2 simple_switch.
- dns es el servidor DNS real simulado con Scapy.

"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from mininet.cli import CLI
from mininet.link import TCLink
from mininet.log import info, setLogLevel
from mininet.net import Mininet
from mininet.node import Node


SCRIPT_DIR = Path(__file__).resolve().parent
P4_JSON = SCRIPT_DIR / "build" / "router.json"
LOG_DIR = "/tmp/dns-cache-p4-logs"

THRIFT_PORTS = {"s1": 9090}
DEVICE_IDS = {"s1": 0}


def _wait_for_log_line(log_path: str, substring: str, timeout: float = 8.0) -> bool:
    """
    Espera hasta que el archivo de log indicado contenga la subcadena dada,
    o hasta agotar el timeout y devuelve True si la encontró.
    """
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            with open(log_path) as f:
                content = f.read()
                if substring in content:
                    return True
        except FileNotFoundError:
            pass

        time.sleep(0.2)

    try:
        with open(log_path) as f:
            content = f.read().strip()

        info(f"[!] Timeout esperando '{substring}' en {log_path}\n")
        info(f"    Contenido del log: {content[:500] or '(vacío)'}\n")

    except FileNotFoundError:
        info(f"[!] Timeout: el archivo {log_path} nunca fue creado\n")

    return False


def _wait_for_updater_ready(timeout: float = 5.0) -> bool:
    """
    Espera a que el updater dinámico escriba su línea de 'escuchando'
    en /tmp/dns_updater.log
    """
    return _wait_for_log_line(
        "/tmp/dns_updater.log",
        "escuchando",
        timeout=timeout,
    )


def _start_dns_server_in_host(dns_host, log_path: str):
    """
    Levanta dns_server.py dentro del host dns de Mininet
    """
    dns_server_path = str(SCRIPT_DIR / "dns_server.py")

    # Crear/limpiar el log antes de arrancar el proceso.
    dns_log = open(log_path, "w")

    proc = dns_host.popen(
        ["sudo", "-E", "/usr/bin/python3", "-u", dns_server_path],
        stdout=dns_log,
        stderr=subprocess.STDOUT,
    )

    return proc

# Nodo P4 para Mininet

class P4Switch(Node):
    """Nodo Mininet que ejecuta BMv2 simple_switch."""

    def __init__(self, name, json_path, thrift_port, device_id, **kwargs):
        kwargs["inNamespace"] = False
        super().__init__(name, **kwargs)

        self.json_path = str(json_path)
        self.thrift_port = thrift_port
        self.device_id = device_id
        self.sw_proc = None

    def start(self, controllers=None):
        os.makedirs(LOG_DIR, exist_ok=True)
        log_file = os.path.join(LOG_DIR, f"{self.name}.log")

        iface_args = []

        for port, intf in sorted(self.intfs.items()):
            if port == 0:
                continue

            iface_args += ["-i", f"{port}@{intf.name}"]

        cmd = (
            [
                "simple_switch",
                "--device-id",
                str(self.device_id),
                "--thrift-port",
                str(self.thrift_port),
                "--log-console",
            ]
            + iface_args
            + [self.json_path]
        )

        info(f"{self.name}: {' '.join(cmd)}\n")

        self.sw_proc = subprocess.Popen(
            cmd,
            stdout=open(log_file, "w"),
            stderr=subprocess.STDOUT,
        )

        time.sleep(2)

        if self.sw_proc.poll() is not None:
            sys.exit(
                f"Error — {self.name} terminó prematuramente. "
                f"Revise el log: {log_file}"
            )

    def stop(self, deleteIntfs=True):
        if self.sw_proc:
            self.sw_proc.terminate()
            self.sw_proc.wait()

        super().stop(deleteIntfs=deleteIntfs)

    def attach(self, intf):
        pass

    def detach(self, intf):
        pass


# Config de hosts

HOSTS = {
    "h1": {
        "ip": "10.0.1.1/24",
        "mac": "08:00:00:00:01:11",
        "gw": "10.0.1.254",
        "gw_mac": "08:00:00:00:01:00",
    },
    "h2": {
        "ip": "10.0.1.2/24",
        "mac": "08:00:00:00:01:22",
        "gw": "10.0.1.254",
        "gw_mac": "08:00:00:00:01:00",
    },
    "h3": {
        "ip": "10.0.1.3/24",
        "mac": "08:00:00:00:01:33",
        "gw": "10.0.1.254",
        "gw_mac": "08:00:00:00:01:00",
    },
    "h4": {
        "ip": "10.0.1.4/24",
        "mac": "08:00:00:00:01:44",
        "gw": "10.0.1.254",
        "gw_mac": "08:00:00:00:01:00",
    },
    "dns": {
        "ip": "10.0.1.100/24",
        "mac": "08:00:00:00:01:99",
        "gw": "10.0.1.254",
        "gw_mac": "08:00:00:00:01:00",
    },
}


def configure_hosts(net: Mininet):
    """Configura gateway y ARP estático en cada host."""
    info("Configurando rutas y ARP estático en hosts\n")

    for name, cfg in HOSTS.items():
        host = net.get(name)
        iface = f"{name}-eth0"

        host.cmd(f"ip route add default via {cfg['gw']} dev {iface}")
        host.cmd(f"arp -i {iface} -s {cfg['gw']} {cfg['gw_mac']}")

        # ARP estático directo hacia el servidor DNS para evitar problemas al inicio.
        if name != "dns":
            host.cmd(f"arp -i {iface} -s 10.0.1.100 {HOSTS['dns']['mac']}")

        # ARP estático hacia cada cliente desde el servidor DNS.
        if name == "dns":
            for client in ["h1", "h2", "h3", "h4"]:
                client_ip = HOSTS[client]["ip"].split("/")[0]
                host.cmd(f"arp -i {iface} -s {client_ip} {HOSTS[client]['mac']}")


# Construcción de la topología

def create_topology() -> Mininet:
    """Construye la topología Mininet."""
    net = Mininet(controller=None, link=TCLink, autoSetMacs=False)

    info("Creando switch P4\n")

    net.addSwitch(
        "s1",
        cls=P4Switch,
        json_path=P4_JSON,
        thrift_port=THRIFT_PORTS["s1"],
        device_id=DEVICE_IDS["s1"],
    )

    info("Creando clientes DNS y servidor DNS\n")

    net.addHost("h1", ip=HOSTS["h1"]["ip"], mac=HOSTS["h1"]["mac"])
    net.addHost("h2", ip=HOSTS["h2"]["ip"], mac=HOSTS["h2"]["mac"])
    net.addHost("h3", ip=HOSTS["h3"]["ip"], mac=HOSTS["h3"]["mac"])
    net.addHost("h4", ip=HOSTS["h4"]["ip"], mac=HOSTS["h4"]["mac"])
    net.addHost("dns", ip=HOSTS["dns"]["ip"], mac=HOSTS["dns"]["mac"])

    info("Creando enlaces\n")

    h1 = net.get("h1")
    h2 = net.get("h2")
    h3 = net.get("h3")
    h4 = net.get("h4")
    dns = net.get("dns")
    s1 = net.get("s1")

    net.addLink(h1, s1, port2=1)
    net.addLink(h2, s1, port2=2)
    net.addLink(h3, s1, port2=3)
    net.addLink(h4, s1, port2=4)
    net.addLink(dns, s1, port2=5)

    return net


# Modos de ejecución

def run(auto_test: bool = False, miss_test: bool = False, watch_test: bool = False):
    if not P4_JSON.exists():
        sys.exit(
            f"Error — No se encontró {P4_JSON}.\n"
            "Compile primero con: make"
        )

    setLogLevel("info")
    net = create_topology()

    dns_server_proc = None

    try:
        info("Iniciando red\n")
        net.start()
        configure_hosts(net)

        info("\n-- Topología DNS lista --\n")
        info("Switch P4: s1  thrift=9090\n")
        info("Clientes:  h1, h2, h3, h4\n")
        info("Servidor DNS: dns = 10.0.1.100\n")
        info("Para cargar reglas: python3 controller.py\n\n")
        # Modo auto-test: conectividad + HIT + benchmark de latencia
        if auto_test:
            import controller
            import test_router
            import test_dns_cache
            import test_latency

            info("Modo auto-test: instalando reglas y ejecutando pruebas\n")

            controller.configure_all(load_cache=True)
            time.sleep(1)

            ok = test_router.run_tests(net)

            if ok:
                ok = test_dns_cache.run_hit_tests(net)

            if ok:
                ok = test_latency.run_latency_benchmark(net, with_miss=False)

            if not ok:
                sys.exit(1)

        # Modo miss-test: MISS sin servidor y MISS con servidor
        elif miss_test:
            import controller
            import test_dns_cache
            import test_latency

            info("Modo miss-test: instalando forwarding sin caché\n")

            controller.configure_all(load_cache=False)
            time.sleep(1)

            # Sin caché y sin servidor debe fallar
            ok = test_dns_cache.run_miss_timeout_test(net)

            #Luego se levanta el servidor y el MISS debe responder
            if ok:
                dns_host = net.get("dns")
                info("Levantando servidor DNS simulado\n")

                dns_server_proc = _start_dns_server_in_host(
                    dns_host,
                    "/tmp/dns_server_test.log",
                )

                ready = _wait_for_log_line(
                    "/tmp/dns_server_test.log",
                    "escuchando",
                    timeout=8,
                )

                if not ready:
                    ok = False
                else:
                    ok = test_dns_cache.run_miss_server_test(net)

                    if ok:
                        ok = test_latency.run_miss_benchmark(
                            net,
                            output_file="/tmp/latency_results_miss.txt",
                        )

            if not ok:
                sys.exit(1)

        # Modo watch-test: updater dinámico aprende dominios en vivo
        elif watch_test:
            import controller
            import test_dns_cache
            import test_latency

            info("Modo watch-test: updater dinámico de caché\n")

            #Instalar solo forwarding, caché vacío
            controller.configure_all(load_cache=False)
            time.sleep(1)

            #Verificar que sin caché el dominio no responda todavía
            info("Verificando que el caché esté vacío al inicio...\n")
            h1 = net.get("h1")

            out = h1.cmd(
                "dig +time=1 +tries=1 +noedns @10.0.1.100 example.com"
            )

            if "10.10.10.10" in out:
                info("[!] El caché no estaba vacío al inicio\n")
                sys.exit(1)
            else:
                info("OK — sin caché, example.com no resuelve\n")

            # Levantar el servidor DNS simulado
            dns_host = net.get("dns")
            info("Levantando servidor DNS simulado\n")

            dns_server_proc = _start_dns_server_in_host(
                dns_host,
                "/tmp/dns_server_watch.log",
            )

            ready = _wait_for_log_line(
                "/tmp/dns_server_watch.log",
                "escuchando",
                timeout=8,
            )

            if not ready:
                sys.exit(1)

            info("Servidor DNS simulado corriendo en 10.0.1.100\n")

            #Activar updater dinámico en hilo de fondo
            controller.run_updater_background(iface="s1-eth5")
            updater_ready = _wait_for_updater_ready(timeout=5)

            if not updater_ready:
                info("[!] El updater no reportó estar listo\n")
                sys.exit(1)

            info("Updater dinámico activo en s1-eth5\n")

            #Se aprenden los tres dominios para que run_hit_test pase
            info("Consultando dominios para que el updater los aprenda desde el servidor...\n")
            h1 = net.get("h1")
            h2 = net.get("h2")
            h3 = net.get("h3")
            h1.cmd("dig +noedns @10.0.1.100 example.com")
            h2.cmd("dig +noedns @10.0.1.100 ucr.ac.cr")
            h3.cmd("dig +noedns @10.0.1.100 cache.test")

            #Da tiempo al updater para procesar las respuestas y escribir registers
            time.sleep(2)
            info("Segunda consulta — ahora deberían responder desde el caché P4...\n")
            ok = test_dns_cache.run_hit_tests(net)

            if ok:
                ok = test_latency.run_watch_benchmark(
                    net,
                    output_file="/tmp/latency_results_watch.txt",
                )

            if ok:
                info("watch-test: el updater aprendió los dominios correctamente.\n")
            else:
                info("[!] watch-test falló — revise los logs del updater.\n")
                sys.exit(1)

        # Sin flags: CLI interactiva
        else:
            CLI(net)

    finally:
        if dns_server_proc is not None:
            try:
                dns_server_proc.terminate()
                dns_server_proc.wait(timeout=2)
            except Exception:
                try:
                    dns_server_proc.kill()
                except Exception:
                    pass

        info("Deteniendo red\n")
        net.stop()

# Punto de entrada

def main():
    parser = argparse.ArgumentParser(
        description="Topología Mininet para Proyecto A: Caché DNS en P4"
    )

    parser.add_argument(
        "--auto-test",
        action="store_true",
        help="Instala reglas, prueba conectividad, HIT y benchmark de latencia.",
    )

    parser.add_argument(
        "--miss-test",
        action="store_true",
        help="Prueba el flujo MISS sin y con servidor DNS activo.",
    )

    parser.add_argument(
        "--watch-test",
        action="store_true",
        help="Prueba el updater dinámico: aprende dominios desde respuestas reales.",
    )

    args = parser.parse_args()

    run(
        auto_test=args.auto_test,
        miss_test=args.miss_test,
        watch_test=args.watch_test,
    )


if __name__ == "__main__":
    main()