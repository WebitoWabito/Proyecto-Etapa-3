#!/usr/bin/env python3
"""
test_router.py

Estas pruebas verifican la primera etapa del proyecto:
    - h1, h2, h3 y h4 pueden comunicarse con el servidor DNS.
    - El tráfico pasa por el switch P4 s1.
    - Todavía no se prueba caché DNS.

"""

import re


DNS_SERVER_IP = "10.0.1.100"

PING_TESTS = [
    ("h1", DNS_SERVER_IP, True, "h1 -> servidor DNS"),
    ("h2", DNS_SERVER_IP, True, "h2 -> servidor DNS"),
    ("h3", DNS_SERVER_IP, True, "h3 -> servidor DNS"),
    ("h4", DNS_SERVER_IP, True, "h4 -> servidor DNS"),
]


def _packet_loss(output: str) -> int | None:
    """
    Extrae el porcentaje de pérdida de la salida de ping.
    """
    match = re.search(r"(\d+)% packet loss", output)

    if not match:
        return None

    return int(match.group(1))


def _ttl_values(output: str) -> list[int]:
    """
    Extrae valores TTL observados en respuestas ICMP.
    """
    return [int(value) for value in re.findall(r"ttl=(\d+)", output)]


def run_tests(net) -> bool:
    """
    Ejecuta pruebas usando los objetos Host de Mininet.
    Devuelve True si todas las pruebas pasan.
    """
    print("\n=== Pruebas Conectividad hacia DNS ===\n")

    all_ok = True

    for src_name, dst_ip, should_work, description in PING_TESTS:
        host = net.get(src_name)

        print(f"--- {description} ---")
        output = host.cmd(f"ping -c 3 -W 1 {dst_ip}")

        loss = _packet_loss(output)
        ttls = _ttl_values(output)

        if should_work:
            passed = loss == 0
            status = "OK" if passed else "FALLÓ"
            ttl_text = f" TTL observado: {ttls[0]}" if ttls else ""

            print(f"Resultado esperado: conectividad. Resultado: {status}.{ttl_text}")
        else:
            passed = loss == 100
            status = "OK" if passed else "FALLÓ"

            print(f"Resultado esperado: descarte. Resultado: {status}.")

        if not passed:
            all_ok = False
            print("Salida de ping:")
            print(output)

        print()

    if all_ok:
        print("Todas las pruebas básicas de conectividad pasaron correctamente.\n")
    else:
        print("Al menos una prueba falló. Revisar controller.py, puertos o ARP.\n")

    return all_ok


def main():
    print("Este archivo se usa automáticamente con: sudo python3 topology.py --auto-test")
    print("Para pruebas manuales, levante la red y use comandos ping en Mininet.")


if __name__ == "__main__":
    main()