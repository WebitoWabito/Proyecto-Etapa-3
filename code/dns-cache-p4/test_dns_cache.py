#!/usr/bin/env python3
"""
test_dns_cache.py

Estas pruebas se ejecutan desde la CLI de Mininet usando los hosts ya creados.

Prueba:
    1. HIT desde caché:
       - Se asume que controller.py cargó la caché.
       - NO requiere dns_server.py.
       - Los dominios deben responder directamente desde el switch P4.

    2. MISS con servidor:
       - Se asume que controller.py --no-cache fue usado.
       - Requiere dns_server.py levantado en el host dns.
       - El switch debe reenviar al servidor DNS real/simulado.
"""

import re


DNS_SERVER_IP = "10.0.1.100"

CACHE_DOMAINS = [
    ("h1", "example.com", "10.10.10.10"),
    ("h2", "ucr.ac.cr", "10.20.20.20"),
    ("h3", "cache.test", "10.30.30.30"),
]


def _extract_answer_ip(output: str) -> str | None:
    """
    Extrae la IP de la sección answer de dig
    """
    match = re.search(r"\s+IN\s+A\s+(\d+\.\d+\.\d+\.\d+)", output)
    if not match:
        return None
    return match.group(1)


def _extract_query_time(output: str) -> int | None:
    """
    Extrae el query time de dig en msec
    """
    match = re.search(r"Query time:\s+(\d+)\s+msec", output)
    if not match:
        return None
    return int(match.group(1))


def run_hit_tests(net) -> bool:
    """
    Prueba que los dominios cacheados respondan directamente desde el switch
    """
    print("\n=== Pruebas DNS HIT desde caché P4 ===\n")

    all_ok = True

    for host_name, domain, expected_ip in CACHE_DOMAINS:
        host = net.get(host_name)

        print(f"--- {host_name} consulta {domain} ---")
        output = host.cmd(f"dig +noedns @{DNS_SERVER_IP} {domain}")

        answer_ip = _extract_answer_ip(output)
        query_time = _extract_query_time(output)

        passed = answer_ip == expected_ip

        if passed:
            print(
                f"Resultado: OK. {domain} -> {answer_ip}. "
                f"Query time: {query_time} ms."
            )
        else:
            all_ok = False
            print("Resultado: FALLÓ.")
            print(f"IP esperada: {expected_ip}")
            print(f"IP recibida: {answer_ip}")
            print("Salida de dig:")
            print(output)

        print()

    if all_ok:
        print("Todas las pruebas HIT pasaron correctamente.\n")
    else:
        print("Al menos una prueba HIT falló.\n")

    return all_ok


def run_miss_timeout_test(net) -> bool:
    """
    Se prueba que, sin caché y sin servidor DNS, la consulta falla.
    Esta prueba debe ejecutarse después de cargar controller.py --no-cache
    y sin levantar dns_server.py.
    """
    print("\n=== Prueba DNS MISS sin servidor ===\n")

    host = net.get("h1")
    output = host.cmd(f"dig +time=1 +tries=1 +noedns @{DNS_SERVER_IP} example.com")

    passed = "no servers could be reached" in output or "timed out" in output

    if passed:
        print("Resultado: OK. La consulta falló porque no había caché ni servidor DNS.")
    else:
        print("Resultado: FALLÓ. Se esperaba timeout.")
        print(output)

    print()
    return passed


def run_miss_server_test(net) -> bool:
    """
    Se prueba que, sin caché pero con dns_server.py, la consulta responde.
    Esta prueba debe ejecutarse después de dns python3 dns_server.py &
    """
    print("\n=== Prueba DNS MISS con servidor ===\n")

    host = net.get("h1")
    output = host.cmd(f"dig +noedns @{DNS_SERVER_IP} example.com")

    answer_ip = _extract_answer_ip(output)
    query_time = _extract_query_time(output)

    passed = answer_ip == "10.10.10.10"

    if passed:
        print(
            f"Resultado: OK. example.com -> {answer_ip}. "
            f"Query time: {query_time} ms."
        )
    else:
        print("Resultado: FALLÓ.")
        print(output)

    print()
    return passed


def main():
    print("Este archivo se importa desde topology.py o se usa manualmente desde Mininet.")
    print("No se debe ejecutar directamente fuera de Mininet.")


if __name__ == "__main__":
    main()