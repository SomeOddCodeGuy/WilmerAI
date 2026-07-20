## Third Party Licensing Section

This folder contains the licenses, pulled directly from the relevant repositories, of libraries called within
requirements.txt and utilized via Imports in WilmerAI.

Wilmer does not modify or extend any of those packages, but for due diligence the author is including their full text
licensing within the project.

### Current Libraries Utilized:

#### Flask:

_Last Updated: 2024-06-23_

* License Type: `BSD 3-Clause "New" or "Revised" License`
* Code: https://github.com/pallets/flask/
* License: https://github.com/pallets/flask/blob/main/LICENSE.txt

#### requests:

_Last Updated: 2024-06-23_

* License Type: `Apache License 2.0`
* Code: https://github.com/psf/requests
* License: https://github.com/psf/requests/blob/main/LICENSE

#### urllib3:

_Last Updated: 2024-06-23_

* License Type: `MIT License`
* Code: https://github.com/urllib3/urllib3/
* License: https://github.com/urllib3/urllib3/blob/main/LICENSE.txt

#### jinja:

_Last Updated: 2024-08-17_

* License Type: `BSD 3-Clause "New" or "Revised" License`
* Code: https://github.com/pallets/jinja
* License: https://github.com/pallets/jinja/blob/main/LICENSE.txt

#### pillow:

_Last Updated: 2026-03-29_

* License Type: `MIT-CMU`
* Code: https://github.com/python-pillow/Pillow/
* License: https://github.com/python-pillow/Pillow/blob/main/LICENSE

#### eventlet:

_Last Updated: 2026-03-29_

* License Type: `MIT License`
* Code: https://github.com/eventlet/eventlet
* License: https://github.com/eventlet/eventlet/blob/master/LICENSE

#### cryptography:

_Last Updated: 2026-03-29_

* License Type: `Apache License 2.0 / BSD 3-Clause` (dual-licensed)
* Code: https://github.com/pyca/cryptography
* License: https://github.com/pyca/cryptography/blob/main/LICENSE

#### waitress:

_Last Updated: 2026-03-29_

* License Type: `Zope Public License (ZPL) Version 2.1`
* Code: https://github.com/Pylons/waitress
* License: https://github.com/Pylons/waitress/blob/main/LICENSE.txt

#### mcp:

_Last Updated: 2026-05-30_

* License Type: `MIT License`
* Code: https://github.com/modelcontextprotocol/python-sdk
* License: https://github.com/modelcontextprotocol/python-sdk/blob/main/LICENSE
* Note: The official Model Context Protocol Python SDK, used by the `MCPToolCall` workflow node to communicate with MCP servers over stdio, SSE, and streamable HTTP transports.

#### PySocks:

_Last Updated: 2026-05-30_

* License Type: `BSD 3-Clause "New" or "Revised" License`
* Code: https://github.com/Anorov/PySocks
* License: https://github.com/Anorov/PySocks/blob/master/LICENSE
* Note: SOCKS4/SOCKS5 proxy client. Required by `requests` when the `WebFetch` workflow node uses a `socks5://` or `socks4://` proxy URL; loaded transparently by `requests` when a SOCKS proxy is configured.
