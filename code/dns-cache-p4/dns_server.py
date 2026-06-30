#!/usr/bin/env python3
"""
dns_server.py — Servidor DNS simple para el Proyecto A

Responde consultas DNS tipo A para dominios controlados.
Debe ejecutarse dentro del host 'dns' de Mininet.
"""

from scapy.all import DNS, DNSQR, DNSRR, IP, UDP, sniff, send


DNS_RECORDS = {
    "example.com.": "10.10.10.10",
    "ucr.ac.cr.": "10.20.20.20",
    "cache.test.": "10.30.30.30",
}


def handle_packet(pkt):
    if not (pkt.haslayer(IP) and pkt.haslayer(UDP) and pkt.haslayer(DNS)):
        return

    dns = pkt[DNS]

    if dns.qr != 0:
        return

    if dns.qd is None:
        return

    qname = dns.qd.qname.decode()
    qtype = dns.qd.qtype

    print(f"Consulta recibida: {qname} tipo={qtype}")

    if qtype != 1:
        print("Solo se responde tipo A.")
        return

    ip_answer = DNS_RECORDS.get(qname)

    if ip_answer is None:
        print(f"No hay registro para {qname}")
        return

    response = (
        IP(src=pkt[IP].dst, dst=pkt[IP].src)
        / UDP(sport=53, dport=pkt[UDP].sport)
        / DNS(
            id=dns.id,
            qr=1,
            aa=1,
            rd=dns.rd,
            ra=1,
            qd=dns.qd,
            ancount=1,
            an=DNSRR(
                rrname=qname,
                type="A",
                ttl=60,
                rdata=ip_answer,
            ),
        )
    )

    print(f"Respondiendo: {qname} -> {ip_answer}")
    send(response, verbose=False)


def main():
    print("Servidor DNS simulado escuchando en UDP puerto 53...", flush=True)
    sniff(filter="udp port 53", prn=handle_packet, store=False)


if __name__ == "__main__":
    main()