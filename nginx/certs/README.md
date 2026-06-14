# TLS Certificates

Place `fullchain.pem` and `privkey.pem` here before using
`docker-compose.tls.yml`.

The default HTTP production compose file does not mount or reference these
files, so missing certificates must not block normal HTTP startup.
