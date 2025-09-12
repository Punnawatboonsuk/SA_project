import socket
import dns.resolver

def force_custom_dns(hostname):
    resolver = dns.resolver.Resolver()
    resolver.nameservers = ["8.8.8.8", "1.1.1.1"]  # Google + Cloudflare DNS
    answer = resolver.resolve(hostname, "A")[0]
    return str(answer)

# Override socket.getaddrinfo to use our resolver
_orig_getaddrinfo = socket.getaddrinfo

def custom_getaddrinfo(host, port, *args, **kwargs):
    try:
        ip = force_custom_dns(host)
        return _orig_getaddrinfo(ip, port, *args, **kwargs)
    except Exception:
        return _orig_getaddrinfo(host, port, *args, **kwargs)