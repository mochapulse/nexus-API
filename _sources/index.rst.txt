Nexus API
=========

FastAPI backend for the Nexus platform — health checks, telemetry collection,
and power-management controls. All business routes are served under the
versioned ``/api/v1`` prefix (protected by an ``X-API-Key`` header); the root
and the API root redirect to the Swagger UI at ``/docs``, and the favicon
stays as a standalone root route.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   api
