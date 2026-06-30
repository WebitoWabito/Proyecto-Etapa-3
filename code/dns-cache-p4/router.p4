// router.p4
//
// Funcionalidad:
//   - Router IPv4 básico.
//   - Parser Ethernet + IPv4 + UDP.
//   - Parser DNS.
//   - Caché simplificada con registers.
//   - Contadores DNS query/response/hit/miss.
//   - En HIT, el switch genera una respuesta DNS directa.
//   - En MISS, el paquete se reenvía al servidor DNS real.
//   - La respuesta directa solo está pensada para dominios controlados:
//       example.com
//       ucr.ac.cr
//       cache.test

#include <core.p4>
#include <v1model.p4>

const bit<16> TYPE_IPV4 = 0x0800;
const bit<8>  IP_PROTO_UDP = 17;
const bit<16> UDP_PORT_DNS = 53;

const bit<32> CACHE_MASK = 0x000003ff;
const bit<16> DNS_ANSWER_SIZE = 16;

const bit<32> DNS_KEY_EXAMPLE = 0x07657861; // 07 'e' 'x' 'a'
const bit<32> DNS_KEY_UCR     = 0x03756372; // 03 'u' 'c' 'r'
const bit<32> DNS_KEY_CACHE   = 0x05636163; // 05 'c' 'a' 'c'

typedef bit<9>  egressSpec_t;
typedef bit<48> macAddr_t;
typedef bit<32> ip4Addr_t;

/*Headers*/

header ethernet_t {
    macAddr_t dstAddr;
    macAddr_t srcAddr;
    bit<16>   etherType;
}

header ipv4_t {
    bit<4>    version;
    bit<4>    ihl;
    bit<8>    diffserv;
    bit<16>   totalLen;
    bit<16>   identification;
    bit<3>    flags;
    bit<13>   fragOffset;
    bit<8>    ttl;
    bit<8>    protocol;
    bit<16>   hdrChecksum;
    ip4Addr_t srcAddr;
    ip4Addr_t dstAddr;
}

header udp_t {
    bit<16> srcPort;
    bit<16> dstPort;
    bit<16> length_;
    bit<16> checksum;
}

/*
 * Cabecera DNS fija de 12 bytes.
 */
header dns_t {
    bit<16> id;
    bit<1>  qr;
    bit<4>  opcode;
    bit<1>  aa;
    bit<1>  tc;
    bit<1>  rd;
    bit<1>  ra;
    bit<3>  z;
    bit<4>  rcode;
    bit<16> qdcount;
    bit<16> ancount;
    bit<16> nscount;
    bit<16> arcount;
}

/*
 * Primeros 4 bytes del nombre DNS codificado.
 *
 * example.com:
 *   07 65 78 61 ...
 *
 * ucr.ac.cr:
 *   03 75 63 72 ...
 *
 * cache.test:
 *   05 63 61 63 ...
 */
header dns_name_key_t {
    bit<32> key;
}

/*
 * Resto de la pregunta DNS.
 * DNS usa nombres de longitud variable. Para poder construir una respuesta
 * válida, conservamos la pregunta completa de cada dominio controlado.
 * Ya extraemos los primeros 4 bytes en dns_name_key_t, por eso aquí
 * solo se parsea el resto.
 */

header dns_question_rest_example_t {
    bit<104> data; // example.com: 17 bytes total, faltan 13 bytes = 104 bits
}

header dns_question_rest_ucr_t {
    bit<88> data; // ucr.ac.cr: 15 bytes total, faltan 11 bytes = 88 bits
}

header dns_question_rest_cache_t {
    bit<96> data; // cache.test: 16 bytes total, faltan 12 bytes = 96 bits
}

/*
 * Answer DNS tipo A.
 *
 * name_ptr = 0xc00c:
 *   puntero al nombre de dominio ubicado en la sección QUESTION.
 *
 * type_ = 1:
 *   registro tipo A.
 *
 * class_ = 1:
 *   IN.
 *
 * rdlength = 4:
 *   IPv4 tiene 4 bytes.
 */
header dns_answer_t {
    bit<16>   name_ptr;
    bit<16>   type_;
    bit<16>   class_;
    bit<32>   ttl;
    bit<16>   rdlength;
    ip4Addr_t rdata;
}

struct metadata {
    bit<32>   cache_index;
    bit<1>    cache_valid_value;
    ip4Addr_t cached_ip;
    bit<1>    replied_from_cache;
}

struct headers {
    ethernet_t                  ethernet;
    ipv4_t                      ipv4;
    udp_t                       udp;
    dns_t                       dns;
    dns_name_key_t              dns_name_key;

    dns_question_rest_example_t dns_question_rest_example;
    dns_question_rest_ucr_t     dns_question_rest_ucr;
    dns_question_rest_cache_t   dns_question_rest_cache;

    dns_answer_t                dns_answer;
}

/*Parser*/

parser MyParser(packet_in packet,
                out headers hdr,
                inout metadata meta,
                inout standard_metadata_t standard_metadata) {

    state start {
        transition parse_ethernet;
    }

    state parse_ethernet {
        packet.extract(hdr.ethernet);

        transition select(hdr.ethernet.etherType) {
            TYPE_IPV4: parse_ipv4;
            default:   accept;
        }
    }

    state parse_ipv4 {
        packet.extract(hdr.ipv4);

        transition select(hdr.ipv4.protocol) {
            IP_PROTO_UDP: parse_udp;
            default:      accept;
        }
    }

    state parse_udp {
        packet.extract(hdr.udp);

        transition select(hdr.udp.dstPort) {
            UDP_PORT_DNS: parse_dns;
            default:      accept;
        }
    }

    state parse_dns {
        packet.extract(hdr.dns);

        /*
         * Solo se parsea el nombre cuando es consulta DNS.
         */
        transition select(hdr.dns.qr) {
            0:       parse_dns_name_key;
            default: accept;
        }
    }

    state parse_dns_name_key {
        packet.extract(hdr.dns_name_key);

        transition select(hdr.dns_name_key.key) {
            DNS_KEY_EXAMPLE: parse_dns_question_rest_example;
            DNS_KEY_UCR:     parse_dns_question_rest_ucr;
            DNS_KEY_CACHE:   parse_dns_question_rest_cache;
            default:         accept;
        }
    }

    state parse_dns_question_rest_example {
        packet.extract(hdr.dns_question_rest_example);
        transition accept;
    }

    state parse_dns_question_rest_ucr {
        packet.extract(hdr.dns_question_rest_ucr);
        transition accept;
    }

    state parse_dns_question_rest_cache {
        packet.extract(hdr.dns_question_rest_cache);
        transition accept;
    }
}

/*checksum verify*/

control MyVerifyChecksum(inout headers hdr, inout metadata meta) {
    apply {}
}

/*ingress*/

control MyIngress(inout headers hdr,
                  inout metadata meta,
                  inout standard_metadata_t standard_metadata) {

    counter(1024, CounterType.packets) dns_query_counter;
    counter(1024, CounterType.packets) dns_response_counter;

    counter(1024, CounterType.packets) dns_hit_counter;
    counter(1024, CounterType.packets) dns_miss_counter;

    register<bit<1>>(1024) cache_valid;
    register<ip4Addr_t>(1024) cache_ip;

    action drop() {
        mark_to_drop(standard_metadata);
    }

    action ipv4_forward(macAddr_t dstAddr, macAddr_t srcAddr, egressSpec_t port) {
        hdr.ethernet.dstAddr = dstAddr;
        hdr.ethernet.srcAddr = srcAddr;
        standard_metadata.egress_spec = port;
        hdr.ipv4.ttl = hdr.ipv4.ttl - 1;
    }

    action dns_cache_reply(ip4Addr_t cached_ip) {
        macAddr_t old_eth_src;
        macAddr_t old_eth_dst;
        ip4Addr_t old_ip_src;
        ip4Addr_t old_ip_dst;
        bit<16> old_udp_src;
        bit<16> old_udp_dst;

        old_eth_src = hdr.ethernet.srcAddr;
        old_eth_dst = hdr.ethernet.dstAddr;

        old_ip_src = hdr.ipv4.srcAddr;
        old_ip_dst = hdr.ipv4.dstAddr;

        old_udp_src = hdr.udp.srcPort;
        old_udp_dst = hdr.udp.dstPort;

        /*
         * Ethernet:
         * La respuesta sale desde la MAC a la que iba dirigida la consulta
         * hacia la MAC del cliente.
         */
        hdr.ethernet.srcAddr = old_eth_dst;
        hdr.ethernet.dstAddr = old_eth_src;

        /*
         * IPv4:
         * La respuesta parece venir desde el servidor DNS.
         */
        hdr.ipv4.srcAddr = old_ip_dst;
        hdr.ipv4.dstAddr = old_ip_src;

        /*
         * UDP:
         * La respuesta sale desde puerto 53 hacia el puerto efímero del cliente.
         */
        hdr.udp.srcPort = old_udp_dst;
        hdr.udp.dstPort = old_udp_src;

        /*
         * DNS:
         * Se convierte query en response.
         */
        hdr.dns.qr = 1;
        hdr.dns.aa = 1;
        hdr.dns.tc = 0;
        hdr.dns.ra = 1;
        hdr.dns.z = 0;
        hdr.dns.rcode = 0;

        hdr.dns.qdcount = 1;
        hdr.dns.ancount = 1;
        hdr.dns.nscount = 0;
        hdr.dns.arcount = 0;

        /*
         * Answer tipo A.
         */
        hdr.dns_answer.setValid();
        hdr.dns_answer.name_ptr = 0xc00c;
        hdr.dns_answer.type_ = 1;
        hdr.dns_answer.class_ = 1;
        hdr.dns_answer.ttl = 60;
        hdr.dns_answer.rdlength = 4;
        hdr.dns_answer.rdata = cached_ip;

        /*
         * La respuesta agrega 16 bytes por la sección ANSWER.
         */
        hdr.ipv4.totalLen = hdr.ipv4.totalLen + DNS_ANSWER_SIZE;
        hdr.udp.length_ = hdr.udp.length_ + DNS_ANSWER_SIZE;

        /*
         * En IPv4, UDP cuando checksum = 0 significa que no se usa.
         * Esto evita checksum UDP inválido después de modificar el paquete.
         */
        hdr.udp.checksum = 0;

        /*
         * Respondemos por el mismo puerto por el que entró la consulta.
         */
        standard_metadata.egress_spec = standard_metadata.ingress_port;
        meta.replied_from_cache = 1;
    }

    table ipv4_lpm {
        key = {
            hdr.ipv4.dstAddr: lpm;
        }

        actions = {
            ipv4_forward;
            drop;
            NoAction;
        }

        size = 1024;
        default_action = drop();
    }

    apply {
        meta.replied_from_cache = 0;

        if (hdr.ipv4.isValid()) {

            if (hdr.udp.isValid()) {

                /*
                 * Consulta DNS:
                 * cliente - servidor
                 * UDP dstPort = 53
                 */
                if (hdr.udp.dstPort == UDP_PORT_DNS) {
                    dns_query_counter.count(0);

                    if (hdr.dns_name_key.isValid()) {
                        meta.cache_index = hdr.dns_name_key.key & CACHE_MASK;

                        cache_valid.read(meta.cache_valid_value, meta.cache_index);
                        cache_ip.read(meta.cached_ip, meta.cache_index);

                        /*
                         * Solo se responde directo si
                         * la entrada está marcada como válida
                         * o la pregunta completa fue parseada
                         */
                        if (meta.cache_valid_value == 1 &&
                            (hdr.dns_question_rest_example.isValid() ||
                             hdr.dns_question_rest_ucr.isValid() ||
                             hdr.dns_question_rest_cache.isValid())) {

                            dns_hit_counter.count(0);
                            dns_cache_reply(meta.cached_ip);

                        } else {
                            dns_miss_counter.count(0);
                        }
                    }
                }

                /*
                 * Respuesta DNS:
                 * servidor - cliente
                 * UDP srcPort = 53
                 */
                if (hdr.udp.srcPort == UDP_PORT_DNS && meta.replied_from_cache == 0) {
                    dns_response_counter.count(0);
                }
            }

            /*
             * Si ya se respondió desde caché, no se aplica ipv4_lpm.
             * Si se hace, el paquete se reenviaría como si fuera
             * una consulta normal.
             */
            if (meta.replied_from_cache == 1) {
                /* Respuesta directa desde caché. */
            } else {
                if (hdr.ipv4.ttl > 1) {
                    ipv4_lpm.apply();
                } else {
                    drop();
                }
            }

        } else {
            drop();
        }
    }
}

/*Egress*/

control MyEgress(inout headers hdr,
                 inout metadata meta,
                 inout standard_metadata_t standard_metadata) {
    apply {
        /* No se requiere procesamiento de salida. */
    }
}

/*chcksum compute*/

control MyComputeChecksum(inout headers hdr, inout metadata meta) {
    apply {
        update_checksum(
            hdr.ipv4.isValid(),
            {
                hdr.ipv4.version,
                hdr.ipv4.ihl,
                hdr.ipv4.diffserv,
                hdr.ipv4.totalLen,
                hdr.ipv4.identification,
                hdr.ipv4.flags,
                hdr.ipv4.fragOffset,
                hdr.ipv4.ttl,
                hdr.ipv4.protocol,
                hdr.ipv4.srcAddr,
                hdr.ipv4.dstAddr
            },
            hdr.ipv4.hdrChecksum,
            HashAlgorithm.csum16
        );
    }
}

/*Deparser*/

control MyDeparser(packet_out packet, in headers hdr) {
    apply {
        packet.emit(hdr.ethernet);
        packet.emit(hdr.ipv4);
        packet.emit(hdr.udp);
        packet.emit(hdr.dns);
        packet.emit(hdr.dns_name_key);

        packet.emit(hdr.dns_question_rest_example);
        packet.emit(hdr.dns_question_rest_ucr);
        packet.emit(hdr.dns_question_rest_cache);

        packet.emit(hdr.dns_answer);
    }
}

/*Switch*/

V1Switch(
    MyParser(),
    MyVerifyChecksum(),
    MyIngress(),
    MyEgress(),
    MyComputeChecksum(),
    MyDeparser()
) main;