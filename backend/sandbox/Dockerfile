FROM python:3.12-slim

# The only third-party dependency across every prelude currently in the database
# (checked directly: 3 distinct preludes, sortedcontainers is the only non-stdlib
# import among them). Network is disabled at container runtime, so anything a
# harness needs must be baked in at build time -- there's no installing on the fly.
RUN pip install --no-cache-dir sortedcontainers
