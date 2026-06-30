#!/usr/bin/env python3
"""
test_latency.py

Mide y guarda la latencia de consultas DNS en distintos escenarios:

1. HIT desde caché P4:
   El switch responde directamente desde los registers.

2. MISS con servidor DNS:
   El switch no tiene la entrada en caché y reenvía la consulta al servidor DNS
   simulado con Scapy.

3. WATCH:
   El caché fue aprendido dinámicamente por el updater del controlador.
"""

import argparse
import os
import re
import time


DNS_SERVER_IP = "10.0.1.100"
REPETITIONS = 10

HIT_DOMAINS = [
    ("example.com", "10.10.10.10"),
    ("ucr.ac.cr", "10.20.20.20"),
    ("cache.test", "10.30.30.30"),
]


def _run_dig(host_obj, domain: str, server: str, timeout: int = 2) -> tuple[int | None, str | None]:
    """
    Ejecuta dig desde un host de Mininet.

    Devuelve:
        (query_time_ms, answer_ip)

    Si la consulta falla o hace timeout, devuelve None en los campos que no se
    pudieron extraer.
    """
    cmd = f"dig +noedns +time={timeout} +tries=1 @{server} {domain}"
    output = host_obj.cmd(cmd)

    time_match = re.search(r"Query time:\s+(\d+)\s+msec", output)
    ip_match = re.search(r"\s+IN\s+A\s+(\d+\.\d+\.\d+\.\d+)", output)

    query_time = int(time_match.group(1)) if time_match else None
    answer_ip = ip_match.group(1) if ip_match else None

    return query_time, answer_ip


def _stats(values: list[int]) -> dict:
    """
    Calcula media, mínimo, máximo y cantidad de datos.
    """
    if not values:
        return {
            "mean": None,
            "min": None,
            "max": None,
            "n": 0,
        }

    return {
        "mean": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
        "n": len(values),
    }


def _print_row(label: str, stats: dict):
    """
    Imprime una fila compacta de resultados.
    """
    if stats["mean"] is None:
        print(f"  {label:<35}  sin datos")
        return

    print(
        f"  {label:<35}  "
        f"media={stats['mean']:6.1f} ms   "
        f"min={stats['min']:4d} ms   "
        f"max={stats['max']:4d} ms   "
        f"(n={stats['n']})"
    )


# Mediciones

def measure_hit(net, server: str = DNS_SERVER_IP) -> dict:
    """
    Mide latencia cuando los registros están en caché P4.
    """
    print("\n--- Escenario HIT: respuesta directa desde caché P4 ---")

    results = {}

    for domain, expected_ip in HIT_DOMAINS:
        host = net.get("h1")
        times = []

        for i in range(REPETITIONS):
            query_time, answer_ip = _run_dig(host, domain, server)

            if query_time is not None and answer_ip == expected_ip:
                times.append(query_time)
            else:
                print(
                    f"  [!] consulta {i + 1} de {domain} falló "
                    f"(ip={answer_ip}, time={query_time})"
                )

        stats = _stats(times)
        results[domain] = stats
        _print_row(f"HIT {domain}", stats)

    return results


def measure_miss(net, server: str = DNS_SERVER_IP) -> dict:
    """
    Mide latencia cuando el caché está vacío y el servidor DNS responde.
    En esta prueba se usa example.com porque el servidor dns_server.py ya lo conoce.
    """
    print("\n--- Escenario MISS: reenvío al servidor DNS real/simulado ---")

    host = net.get("h1")
    times = []

    for i in range(REPETITIONS):
        query_time, answer_ip = _run_dig(host, "example.com", server, timeout=5)

        if query_time is not None and answer_ip == "10.10.10.10":
            times.append(query_time)
        else:
            print(
                f"  [!] consulta {i + 1} MISS falló "
                f"(ip={answer_ip}, time={query_time})"
            )

    stats = _stats(times)
    _print_row("MISS example.com", stats)

    return {"example.com": stats}


def measure_no_cache_no_server(net, server: str = DNS_SERVER_IP) -> dict:
    """
    Mide una referencia de timeout cuando no hay caché ni servidor.
    """
    print("\n--- Escenario SIN CACHÉ / SIN SERVIDOR ---")

    host = net.get("h1")
    times = []

    for i in range(3):
        start = time.time()
        query_time, answer_ip = _run_dig(host, "example.com", server, timeout=1)
        elapsed = int((time.time() - start) * 1000)

        measured = query_time if query_time is not None else elapsed
        times.append(measured)

        print(f"  consulta {i + 1}: ~{measured} ms (timeout esperado)")

    stats = _stats(times)
    _print_row("SIN SERVIDOR example.com", stats)

    return {"example.com": stats}


# Salida y guardado

def print_summary(hit: dict, miss: dict, no_cache: dict):
    """
    Imprime una tabla con el resumen de mediciones en consola.
    """
    print("\n" + "=" * 72)
    print("RESUMEN DE LATENCIA — Caché DNS P4")
    print("=" * 72)
    print(f"  {'Escenario':<35}  {'Media':>8}  {'Mín':>6}  {'Máx':>6}  {'N':>4}")
    print("  " + "-" * 67)

    def row(label: str, stats: dict):
        if stats["mean"] is None:
            print(
                f"  {label:<35}  "
                f"{'N/A':>8}  {'N/A':>6}  {'N/A':>6}  {stats['n']:>4}"
            )
        else:
            print(
                f"  {label:<35}  "
                f"{stats['mean']:>7.1f}ms  "
                f"{stats['min']:>5}ms  "
                f"{stats['max']:>5}ms  "
                f"{stats['n']:>4}"
            )

    for domain, stats in hit.items():
        row(f"HIT {domain}", stats)

    for domain, stats in miss.items():
        row(f"MISS {domain}", stats)

    for domain, stats in no_cache.items():
        row(f"SIN SERVIDOR {domain}", stats)

    print("=" * 72)


def save_results(
    hit: dict,
    miss: dict,
    no_cache: dict,
    output_file: str = "/tmp/latency_results.txt",
):
    """
    Guarda los resultados en un archivo de texto.
    """
    with open(output_file, "w") as f:
        f.write("Resultados de latencia — Caché DNS P4\n")
        f.write("=" * 60 + "\n\n")

        if hit:
            f.write("Escenario HIT / respuesta directa desde caché P4:\n")
            for domain, stats in hit.items():
                if stats["mean"] is not None:
                    f.write(
                        f"  {domain}: media={stats['mean']:.1f}ms  "
                        f"min={stats['min']}ms  "
                        f"max={stats['max']}ms  "
                        f"n={stats['n']}\n"
                    )
            f.write("\n")

        if miss:
            f.write("Escenario MISS / reenvío al servidor DNS real-simulado:\n")
            for domain, stats in miss.items():
                if stats["mean"] is not None:
                    f.write(
                        f"  {domain}: media={stats['mean']:.1f}ms  "
                        f"min={stats['min']}ms  "
                        f"max={stats['max']}ms  "
                        f"n={stats['n']}\n"
                    )
            f.write("\n")

        if no_cache:
            f.write("Escenario sin caché ni servidor:\n")
            for domain, stats in no_cache.items():
                if stats["mean"] is not None:
                    f.write(
                        f"  {domain}: media={stats['mean']:.1f}ms  "
                        f"min={stats['min']}ms  "
                        f"max={stats['max']}ms  "
                        f"n={stats['n']}\n"
                    )
            f.write("\n")

    try:
        os.chmod(output_file, 0o666)
    except OSError:
        pass

    print(f"\nResultados guardados en: {os.path.abspath(output_file)}")
    print(f"(si no lo puede abrir su editor, pruebe: sudo cat {output_file})")


# Benchmarks llamados desde topology.py

def run_latency_benchmark(
    net,
    server: str = DNS_SERVER_IP,
    with_miss: bool = True,
    output_file: str = "/tmp/latency_results.txt",
) -> bool:
    """
    Benchmark que mide HIT. Si with_miss=True también mide MISS, pero para
    --auto-test se usa with_miss=False porque no se levanta dns_server.py.
    """
    print("\n=== Benchmark de latencia DNS ===")

    hit_results = measure_hit(net, server)

    miss_results = {}
    if with_miss:
        miss_results = measure_miss(net, server)

    no_cache_results = {}

    print_summary(hit_results, miss_results, no_cache_results)
    save_results(
        hit_results,
        miss_results,
        no_cache_results,
        output_file=output_file,
    )

    return all(stats["n"] > 0 for stats in hit_results.values())


def run_miss_benchmark(
    net,
    server: str = DNS_SERVER_IP,
    output_file: str = "/tmp/latency_results_miss.txt",
) -> bool:
    """
    Benchmark que mide el escenario MISS porque la caché está vacía.
    """
    print("\n=== Benchmark de latencia DNS — MISS ===")

    hit_results = {}
    miss_results = measure_miss(net, server)
    no_cache_results = {}

    print_summary(hit_results, miss_results, no_cache_results)
    save_results(
        hit_results,
        miss_results,
        no_cache_results,
        output_file=output_file,
    )

    return all(stats["n"] > 0 for stats in miss_results.values())


def run_watch_benchmark(
    net,
    server: str = DNS_SERVER_IP,
    output_file: str = "/tmp/latency_results_watch.txt",
) -> bool:
    """
    Benchmark que mide HIT después de que el updater aprendió dinámicamente los dominios.
    """
    print("\n=== Benchmark de latencia DNS — WATCH / caché aprendida ===")

    hit_results = measure_hit(net, server)
    miss_results = {}
    no_cache_results = {}

    print_summary(hit_results, miss_results, no_cache_results)
    save_results(
        hit_results,
        miss_results,
        no_cache_results,
        output_file=output_file,
    )

    return all(stats["n"] > 0 for stats in hit_results.values())


# Entrada standalone

def main():
    parser = argparse.ArgumentParser(
        description="Benchmark de latencia para el caché DNS P4"
    )

    parser.add_argument(
        "--server",
        default=DNS_SERVER_IP,
        help=f"IP del servidor DNS. Default: {DNS_SERVER_IP}",
    )

    args = parser.parse_args()

    print("Este script está pensado para usarse desde topology.py.")
    print("Ejemplos:")
    print("  sudo -E python3 topology.py --auto-test")
    print("  sudo -E python3 topology.py --miss-test")
    print("  sudo -E python3 topology.py --watch-test")
    print()
    print(f"Servidor DNS por defecto: {args.server}")


if __name__ == "__main__":
    main()