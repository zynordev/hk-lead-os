# AVDS deployment

Install the two unit files into `/etc/systemd/system/`, then enable:

```bash
systemctl daemon-reload
systemctl enable --now public-relations-whatsapp.service public-relations-dashboard.service
```

The dashboard remains on `127.0.0.1:8790` until DNS, Caddy and WebAuthn are configured.
